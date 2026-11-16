"""The application workflow, as a LangGraph graph.

        START ──► gap ─────┐
          └────► tailor ───┴──► review (PAUSES for you) ──► finalize ──► END

- gap and tailor are independent, so they run IN PARALLEL.
- review calls interrupt(): the run stops there and waits for your decision.
  Resuming restarts that node from its first line, so it must have no side effects
  before interrupt() (it only builds a payload).
- Nothing leaves the system without your approval. Anything unrecognised counts as "reject".
- Runs live in memory (InMemorySaver) and are lost when the server restarts. A database
  checkpointer is the production upgrade.

Later nodes slot in the same way: a company researcher beside gap/tailor, and an outreach
writer between tailor and review.

The node functions below are plain async functions, so they are testable without LangGraph.
Only build_graph() and RunManager touch LangGraph.
"""
from __future__ import annotations

import asyncio
import operator
import time
import uuid
from typing import Annotated, TypedDict

from ..matching import Profile
from .gap import analyze_gap
from .tailor import tailor_resume


class RunState(TypedDict, total=False):
    job: dict
    resume_text: str
    skills: list[str]
    years: float | None
    gap: dict
    tailored: dict
    decision: dict
    final: dict
    # Parallel nodes each append events; operator.add merges the lists instead of overwriting.
    trace: Annotated[list[dict], operator.add]


def _event(node: str, t0: float, note: str) -> dict:
    return {"node": node, "ms": int((time.perf_counter() - t0) * 1000), "note": note}


# ---- nodes ---------------------------------------------------------------------------

async def gap_node(state: RunState) -> dict:
    t0 = time.perf_counter()
    try:
        profile = Profile(text=state["resume_text"], skills=state["skills"], years=state.get("years"))
        gap = await analyze_gap(profile, state["job"])
        note = f"{gap['verdict']}; advice from {gap['advice_source']}"
    except Exception as e:
        gap, note = {"headline": "Gap analysis failed.", "verdict": "unclear"}, f"failed: {type(e).__name__}"
    return {"gap": gap, "trace": [_event("gap", t0, note)]}


async def tailor_node(state: RunState) -> dict:
    t0 = time.perf_counter()
    try:
        tailored = await tailor_resume(state["resume_text"], state["job"], state["skills"])
        s = tailored["stats"]
        note = (f"{s['rewritten']} rewritten, {s['unchanged']} unchanged, {s['kept_original']} kept original; "
                f"checked by {tailored['checked_by']}")
    except Exception as e:
        tailored = {"bullets": [], "checked_by": "none", "note": "Tailoring failed.", "stats": {}}
        note = f"failed: {type(e).__name__}"
    return {"tailored": tailored, "trace": [_event("tailor", t0, note)]}


def review_payload(state: RunState) -> dict:
    """What you see on the approval screen. Pure: safe to run twice."""
    gap, tailored, job = state.get("gap", {}), state.get("tailored", {}), state["job"]
    return {
        "kind": "approve_application",
        "job": {"id": job["id"], "title": job["title"], "company": job["company"]},
        "headline": gap.get("headline", ""),
        "verdict": gap.get("verdict", "unclear"),
        "advice": gap.get("advice", []),
        "checked_by": tailored.get("checked_by", "none"),
        "note": tailored.get("note", ""),
        "bullets": [{"id": b["id"], "original": b["original"], "final": b["final"],
                     "status": b["status"], "problems": b["problems"],
                     "rejected_rewrite": b["rejected_rewrite"]}
                    for b in tailored.get("bullets", [])],
    }


def review_node(state: RunState) -> dict:
    from langgraph.types import interrupt  # imported here so the rest of this file needs no LangGraph

    decision = interrupt(review_payload(state))  # the run pauses here until you decide
    return {"decision": decision, "trace": [{"node": "review", "ms": 0, "note": "decision received"}]}


def clean_decision(raw, bullets: list[dict]) -> dict:
    """Only an explicit 'approve' counts. Edits must target real bullets and have text."""
    if not isinstance(raw, dict) or str(raw.get("action", "")).lower() != "approve":
        return {"action": "reject", "edits": {}}
    valid = {b["id"] for b in bullets}
    edits: dict[int, str] = {}
    for key, value in (raw.get("edits") or {}).items():
        try:
            bullet_id = int(key)
        except (TypeError, ValueError):
            continue
        text = value.strip()[:400] if isinstance(value, str) else ""
        if bullet_id in valid and text:
            edits[bullet_id] = text
    return {"action": "approve", "edits": edits}


def finalize_node(state: RunState) -> dict:
    bullets = state.get("tailored", {}).get("bullets", [])
    d = clean_decision(state.get("decision"), bullets)
    if d["action"] != "approve":
        return {"final": {"status": "rejected"},
                "trace": [{"node": "finalize", "ms": 0, "note": "rejected: nothing was saved"}]}
    out = []
    for b in bullets:
        edited = b["id"] in d["edits"]
        out.append({"id": b["id"], "text": d["edits"].get(b["id"], b["final"]),
                    "source": "edited by you" if edited else b["status"]})
    return {"final": {"status": "approved", "bullets": out,
                      "text": "\n".join(f"- {x['text']}" for x in out)},
            "trace": [{"node": "finalize", "ms": 0, "note": f"approved ({len(d['edits'])} edited by you)"}]}


# ---- wiring (the only part that needs LangGraph) -------------------------------------

def build_graph():
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(RunState)
    g.add_node("gap", gap_node)
    g.add_node("tailor", tailor_node)
    g.add_node("review", review_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "gap")        # two edges out of START: gap and tailor run in parallel
    g.add_edge(START, "tailor")
    g.add_edge(["gap", "tailor"], "review")   # a list means: wait for BOTH before reviewing
    g.add_edge("review", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=InMemorySaver())  # a checkpointer is required for interrupt()


class RunManager:
    """Starts runs and resumes them. One run = one LangGraph thread."""

    def __init__(self) -> None:
        self._graph = None
        self._waiting: set[str] = set()   # runs paused for approval

    def _g(self):
        if self._graph is None:
            self._graph = build_graph()
        return self._graph

    async def start(self, job: dict, resume_text: str, skills: list[str], years: float | None = None) -> dict:
        run_id = uuid.uuid4().hex[:12]
        config = {"configurable": {"thread_id": run_id}}
        result = await self._g().ainvoke(
            {"job": job, "resume_text": resume_text, "skills": skills, "years": years, "trace": []}, config)
        return self._summarize(run_id, result)

    async def decide(self, run_id: str, decision: dict) -> dict:
        if run_id not in self._waiting:   # unknown, finished, or already decided
            raise KeyError(run_id)
        from langgraph.types import Command

        config = {"configurable": {"thread_id": run_id}}  # must be the same thread id as the pause
        result = await self._g().ainvoke(Command(resume=decision), config)
        return self._summarize(run_id, result)

    def _summarize(self, run_id: str, result: dict) -> dict:
        interrupts = result.get("__interrupt__")
        if interrupts:
            self._waiting.add(run_id)
            first = interrupts[0]
            return {"run_id": run_id, "status": "awaiting_approval",
                    "review": getattr(first, "value", first), "trace": result.get("trace", [])}
        self._waiting.discard(run_id)
        final = result.get("final", {})
        return {"run_id": run_id, "status": final.get("status", "done"), "final": final,
                "trace": result.get("trace", [])}