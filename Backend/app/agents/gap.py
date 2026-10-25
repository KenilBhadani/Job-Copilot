"""Gap Analyzer agent: how close are you to this job, and what should you learn first?

Design rule: facts are computed by code, advice comes from the model, and code checks
the advice before it reaches you.
  - matched / missing skills, coverage, the verdict and the years gap are deterministic,
    so the model can't inflate your chances.
  - the model only writes WHY a missing skill matters and WHAT to learn first.
  - clean_advice() drops skills the model invented, and only lets it say a missing
    skill "builds on" something that is really in your skill list.
  - if the model fails or isn't configured, plain template advice is returned instead.
"""
from __future__ import annotations

from .. import llm_client
from ..matching import Profile

PRIORITIES = {"high", "medium", "low"}

SYSTEM = (
    "You are a practical career coach. Address the candidate as 'you'. For each MISSING skill, "
    "explain briefly why this specific job needs it and what you should do first to learn it. "
    "The verdict was decided by code: never contradict it, and never call the job a strong, "
    "great or well-aligned fit unless the verdict is 'strong fit'. "
    "If the experience gap is significant, say so in the summary. "
    "Reply with ONLY JSON: "
    '{"summary": "<2 sentences on overall fit>", "skills": [{"skill": "<exact name from the missing list>", '
    '"priority": "high|medium|low", "why": "<one sentence about this job>", '
    '"builds_on": "<one skill from the candidate list that helps, or null>", '
    '"learn_first": "<one concrete first step, such as a small project or a topic to study>"}]}. '
    "Rules: only use skills from the missing list; builds_on must come from the candidate list; "
    "do not invent facts about the candidate; do not include links."
)

# If the code says "stretch" or "long shot", the summary may not use these phrases.
OVERSTATE = ("well-aligned", "well aligned", "strong fit", "great fit", "excellent fit",
             "perfect fit", "ideal candidate", "strong match", "perfect match", "great match")


def skill_gap(profile: Profile, job: dict) -> dict:
    """The deterministic part: no model involved."""
    have = {s.lower() for s in profile.skills}
    req, pref = job["skills_required"], job["skills_preferred"]
    matched_req = [s for s in req if s.lower() in have]
    missing_req = [s for s in req if s.lower() not in have]
    matched_pref = [s for s in pref if s.lower() in have]
    missing_pref = [s for s in pref if s.lower() not in have]

    coverage = len(matched_req) / len(req) if req else None
    if len(req) < 3:
        verdict = "unclear"      # a posting naming 0-2 skills says too little to judge
    elif coverage >= 0.75:
        verdict = "strong fit"
    elif coverage >= 0.4:
        verdict = "stretch"
    else:
        verdict = "long shot"

    need = job.get("min_years")
    years = {"needed": need, "have": profile.years,
             "short_by": (need - profile.years) if (need and profile.years is not None and need > profile.years) else 0}
    return {"verdict": verdict, "coverage": coverage,
            "matched_required": matched_req, "missing_required": missing_req,
            "matched_preferred": matched_pref, "missing_preferred": missing_pref, "years": years}


def make_headline(facts: dict, n_req: int) -> str:
    """One sentence built entirely by code, so it can't contradict the numbers."""
    if facts["verdict"] == "unclear":
        return "Unclear: this posting names too few skills to judge your fit."
    line = (f"{facts['verdict'].capitalize()}: you match {len(facts['matched_required'])} "
            f"of {n_req} required skills")
    short = facts["years"]["short_by"]
    if short:
        line += f" and are about {short:g} year{'s' if short != 1 else ''} short on experience"
    return line + "."


def summary_is_consistent(text: str, verdict: str) -> bool:
    """Reject a model summary that oversells the fit the code computed."""
    if verdict in ("stretch", "long shot", "unclear"):
        return not any(p in text.lower() for p in OVERSTATE)
    return True


def _template(skill: str, required: set[str]) -> dict:
    is_req = skill in required
    return {"skill": skill, "priority": "high" if is_req else "low",
            "why": "Listed as required for this role." if is_req else "Listed as a nice-to-have for this role.",
            "builds_on": None,
            "learn_first": f"Build one small project that uses {skill} and add it to your resume."}


def _s(value, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) else ""


def clean_advice(raw, targets: list[str], required: set[str], have: list[str]) -> list[dict]:
    """Check the model's answer against the facts. Returns one entry per target skill, in order."""
    have_map = {s.lower(): s for s in have}
    items = raw.get("skills") if isinstance(raw, dict) else raw
    by_skill = {}
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                by_skill[_s(it.get("skill"), 60).lower()] = it  # unknown skills are simply never looked up

    out = []
    for skill in targets:
        base = _template(skill, required)
        it = by_skill.get(skill.lower())
        if it is None:
            out.append(base)
            continue
        priority = _s(it.get("priority"), 10).lower()
        if priority not in PRIORITIES:
            priority = base["priority"]
        if skill not in required and priority == "high":
            priority = "medium"  # a nice-to-have can't be the top priority
        out.append({
            "skill": skill, "priority": priority,
            "why": _s(it.get("why"), 240) or base["why"],
            "builds_on": have_map.get(_s(it.get("builds_on"), 60).lower()),  # None unless it's truly your skill
            "learn_first": _s(it.get("learn_first"), 300) or base["learn_first"],
        })
    return out


async def analyze_gap(profile: Profile, job: dict, use_llm: bool = True) -> dict:
    facts = skill_gap(profile, job)
    required = set(job["skills_required"])
    targets = (facts["missing_required"] + facts["missing_preferred"])[:10]
    n_req = len(job["skills_required"])
    headline = make_headline(facts, n_req)
    summary = headline
    advice = [_template(s, required) for s in targets]
    source = "template"

    if targets and use_llm and llm_client.available():
        exp = ""
        if facts["years"]["needed"] and profile.years is not None:
            exp = (f"\nExperience: the job asks for {facts['years']['needed']}+ years; "
                   f"the candidate has {profile.years:g}.")
        user = (f"<job>\nTitle: {job['title']} at {job['company']}\n{(job['description'] or '')[:3500]}\n</job>\n\n"
                f"Candidate skills: {', '.join(profile.skills) or 'none listed'}{exp}\n"
                f"Verdict (decided by code, do not contradict it): {facts['verdict']}\n"
                f"Missing skills to advise on: {', '.join(targets)}")
        try:
            raw = await llm_client.ask_json(SYSTEM, user, max_tokens=2500)
            advice = clean_advice(raw, targets, required, profile.skills)
            source = "model"
            model_summary = _s(raw.get("summary"), 400) if isinstance(raw, dict) else ""
            if model_summary and summary_is_consistent(model_summary, facts["verdict"]):
                summary = model_summary
        except Exception:
            pass  # keep the template advice: the app must work without the model

    return {"job_id": job["id"], "title": job["title"], "company": job["company"],
            "headline": headline, "summary": summary, "advice": advice,
            "advice_source": source, **facts}