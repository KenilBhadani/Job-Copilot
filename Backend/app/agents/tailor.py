"""Resume Tailor + Critic: rewrite your bullets for one job without inventing anything.

Safety design, in layers:
  1. CODE CHECK (no model): a rewrite may not contain a number, skill/tool, tool-like name
     or ownership verb ("led", "architected"...) that the ORIGINAL bullet doesn't have,
     and may not balloon in length.
  2. CRITIC (model): reads original vs rewrite and flags any claim the original doesn't make.
  3. LOOP: flagged bullets go back to the Tailor with the exact problem, for up to
     MAX_ROUNDS revisions.
  4. SAFE DEFAULT: a bullet that still fails keeps your ORIGINAL text. The rejected
     rewrite is shown to you, never used.
  5. YOU approve the final result (the approval screen comes later).

These checks catch most invented facts but not every possible one (for example a verb
quietly changed from "helped" to "improved"), which is why step 5 exists.
"""
from __future__ import annotations

import re

from .. import llm_client
from ..skills import extract_skills

MAX_BULLETS = 15
MAX_ROUNDS = 2  # revisions after the first attempt

BULLET_RE = re.compile(r"^\s*(?:[-•*–·▪●]|\d+[.)])\s+(.*\S)\s*$")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.]*")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
INFLATION = {"led", "lead", "leading", "managed", "architected", "owned", "spearheaded",
             "headed", "directed", "pioneered", "founded", "orchestrated"}

TAILOR_SYSTEM = (
    "You rewrite resume bullets so they fit one job better. Hard rules: use ONLY facts already "
    "in each original bullet. Never add numbers, tools, technologies, employers, job titles, team "
    "sizes, results, or words like led/managed/architected/owned that the original doesn't have. "
    "You may reword, reorder, tighten, and use the job's own terminology for something the original "
    "already says. Keep each bullet to one line and roughly the same length. If a bullet can't be "
    "improved, return it unchanged. "
    'Reply with ONLY JSON: {"bullets": [{"id": 1, "text": "<rewritten bullet>"}]} covering every id given.'
)

CRITIC_SYSTEM = (
    "You are a strict fact-checker for resumes. For each pair, decide if the REWRITE states anything "
    "that the ORIGINAL does not state or clearly imply: a result, metric, scope, technology, ownership, "
    "team size, or outcome. Rewording, reordering and using the job's terminology for something the "
    "original already says are fine. "
    'Reply with ONLY JSON: {"checks": [{"id": 1, "ok": true, "problem": ""}]} covering every id. '
    "If ok is false, say in one sentence exactly what was added."
)


# ---- pure helpers (no model) -------------------------------------------------------

def extract_bullets(resume_text: str) -> list[str]:
    """Bullet lines from a pasted resume. Falls back to long plain lines if there are no bullets."""
    lines = resume_text.splitlines()
    bullets = [m.group(1).strip() for ln in lines if (m := BULLET_RE.match(ln))]
    if not bullets:
        bullets = [ln.strip() for ln in lines if len(ln.strip()) >= 40]
    return bullets[:MAX_BULLETS]


def _norm(w: str) -> str:
    w = w.lower().rstrip(".")
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def _name_like(text: str) -> set[str]:
    """Tool-like words: two or more capitals (AWS, FastAPI) or a digit (S3, Python3)."""
    out = set()
    for w in WORD_RE.findall(text):
        if sum(c.isupper() for c in w) >= 2 or any(c.isdigit() for c in w):
            out.add(_norm(w))
    return out


def check_rewrite(original: str, rewritten: str) -> list[str]:
    """The code-level check. Returns a list of problems (empty means it passed)."""
    problems = []
    if not rewritten.strip():
        return ["The rewrite is empty."]

    new_nums = {n.replace(",", "") for n in NUM_RE.findall(rewritten)} - \
               {n.replace(",", "") for n in NUM_RE.findall(original)}
    if new_nums:
        problems.append(f"Introduced number(s) not in the original: {', '.join(sorted(new_nums))}.")

    new_skills = set(extract_skills(rewritten)) - set(extract_skills(original))
    if new_skills:
        problems.append(f"Introduced skill(s)/tool(s) not in the original: {', '.join(sorted(new_skills))}.")

    new_names = _name_like(rewritten) - {_norm(w) for w in WORD_RE.findall(original)}
    new_names -= {_norm(s) for s in new_skills}  # already reported above
    if new_names:
        problems.append(f"Introduced name(s) not in the original: {', '.join(sorted(new_names))}.")

    orig_words = {w.lower() for w in WORD_RE.findall(original)}
    new_verbs = {w.lower() for w in WORD_RE.findall(rewritten)} & INFLATION - orig_words
    if new_verbs:
        problems.append(f"Claims stronger ownership than the original: {', '.join(sorted(new_verbs))}.")

    if len(rewritten) > 1.6 * len(original) + 30:
        problems.append("Much longer than the original, which suggests added content.")
    return problems


# ---- model calls ------------------------------------------------------------------

def _job_block(job: dict, have_required: list[str]) -> str:
    return (f"<job>\nTitle: {job['title']} at {job['company']}\n"
            f"Skills the candidate really has that this job wants: {', '.join(have_required) or 'none'}\n"
            f"{(job.get('description') or '')[:2500]}\n</job>")


async def _tailor_pass(job: dict, have_required: list[str], items: list[dict], feedback: dict[int, list[str]]) -> dict[int, str]:
    lines = []
    for it in items:
        lines.append(f"[{it['id']}] {it['original']}")
        if it["id"] in feedback:
            lines.append(f"    Your last attempt was rejected: {' '.join(feedback[it['id']])} "
                         f"Rewrite again using only facts from the original.")
    user = f"{_job_block(job, have_required)}\n\n<resume>\n" + "\n".join(lines) + "\n</resume>"
    raw = await llm_client.ask_json(TAILOR_SYSTEM, user, max_tokens=3000)
    rows = raw.get("bullets") if isinstance(raw, dict) else raw
    out: dict[int, str] = {}
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and isinstance(r.get("text"), str):
            try:
                out[int(r.get("id"))] = r["text"].strip()
            except (TypeError, ValueError):
                continue
    return out


async def _critic_pass(pairs: list[dict]) -> dict[int, str]:
    """Returns {id: problem} for rewrites the critic rejects."""
    user = "<source>\n" + "\n".join(
        f"[{p['id']}] ORIGINAL: {p['original']}\n    REWRITE: {p['rewrite']}" for p in pairs) + "\n</source>"
    raw = await llm_client.ask_json(CRITIC_SYSTEM, user, max_tokens=2000)
    rows = raw.get("checks") if isinstance(raw, dict) else raw
    bad: dict[int, str] = {}
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("ok") is False:
            try:
                bad[int(r.get("id"))] = str(r.get("problem") or "The critic says this adds a claim.")[:240]
            except (TypeError, ValueError):
                continue
    return bad


# ---- the agent ---------------------------------------------------------------------

async def tailor_resume(resume_text: str, job: dict, profile_skills: list[str], use_llm: bool = True) -> dict:
    bullets = extract_bullets(resume_text)
    have = {s.lower() for s in profile_skills}
    have_required = [s for s in job["skills_required"] if s.lower() in have]
    state = [{"id": i + 1, "original": b, "final": b, "status": "unchanged",
              "problems": [], "rejected_rewrite": None} for i, b in enumerate(bullets)]
    result = {"job_id": job["id"], "title": job["title"], "company": job["company"],
              "bullets": state, "checked_by": "none", "attempts": 0, "note": ""}

    if not bullets:
        result["note"] = "No bullet points found. Put each achievement on its own line starting with '-'."
        return _finish(result, job)
    if not (use_llm and llm_client.available()):
        result["note"] = "No model configured, so your bullets are returned unchanged."
        return _finish(result, job)

    pending = list(state)
    feedback: dict[int, list[str]] = {}
    critic_ok = True

    for attempt in range(1, MAX_ROUNDS + 2):
        result["attempts"] = attempt
        try:
            rewrites = await _tailor_pass(job, have_required, pending, feedback)
        except Exception:
            result["note"] = "The model failed, so remaining bullets keep your original text."
            for it in pending:  # nothing was rejected: there was simply no rewrite
                it["status"], it["problems"] = "unchanged", []
            pending = []
            break

        # Layer 1: code checks
        problems: dict[int, list[str]] = {}
        clear: list[dict] = []
        for it in pending:
            text = rewrites.get(it["id"])
            if text is None:
                problems[it["id"]] = ["The tailor returned nothing for this bullet."]
                continue
            found = check_rewrite(it["original"], text)
            if found:
                problems[it["id"]] = found
                it["rejected_rewrite"] = text
            else:
                clear.append({"id": it["id"], "original": it["original"], "rewrite": text})

        # Layer 2: the critic reviews what passed the code check
        if clear and critic_ok:
            try:
                bad = await _critic_pass(clear)
                result["checked_by"] = "code+critic"
            except Exception:
                critic_ok = False
                bad = {}
                result["checked_by"] = "code only"
            for c in clear:
                if c["id"] in bad:
                    problems[c["id"]] = [bad[c["id"]]]
                    next(it for it in pending if it["id"] == c["id"])["rejected_rewrite"] = c["rewrite"]
        elif clear:
            result["checked_by"] = "code only"

        # Accept what passed; the rest go round again, or keep the original
        by_id = {it["id"]: it for it in pending}
        for c in clear:
            if c["id"] not in problems:
                it = by_id[c["id"]]
                same = re.sub(r"\s+", " ", c["rewrite"]).strip() == re.sub(r"\s+", " ", it["original"]).strip()
                it["final"], it["status"] = c["rewrite"], ("unchanged" if same else "rewritten")
                it["rejected_rewrite"], it["problems"] = None, []

        pending = [it for it in pending if it["id"] in problems]
        feedback = {i: p for i, p in problems.items()}
        for it in pending:
            it["problems"] = problems[it["id"]]
        if not pending:
            break

    for it in pending:  # still failing after the last attempt: safe default
        it["final"], it["status"] = it["original"], "kept_original"
    return _finish(result, job)


def _finish(result: dict, job: dict) -> dict:
    bl = result["bullets"]
    result["tailored_text"] = "\n".join(f"- {b['final']}" for b in bl)
    result["stats"] = {s: sum(1 for b in bl if b["status"] == s)
                       for s in ("rewritten", "unchanged", "kept_original")}
    surfaced = set(extract_skills(result["tailored_text"]))
    result["skills_surfaced"] = [s for s in job["skills_required"] if s in surfaced]
    return result