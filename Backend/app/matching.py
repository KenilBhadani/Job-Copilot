"""The matching engine: cheap filters first, then scoring.

score = 50% required-skill coverage + 10% preferred-skill coverage + 40% text similarity
(+ small bonus when a target-role keyword appears in the title).

Text similarity is TF-IDF cosine for Phase 1: no API key, no model download, fully
deterministic. Phase 2 can replace _similarities() with pgvector embeddings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


@dataclass
class Profile:
    text: str
    skills: list[str]
    years: float | None = None
    headline: str | None = None


@dataclass
class Filters:
    locations: list[str] = field(default_factory=list)
    include_remote: bool = True
    remote_only: bool = False
    role_keywords: list[str] = field(default_factory=list)


def _norm_loc(s: str) -> str:
    return (s or "").lower().replace("bangalore", "bengaluru").replace("gurgaon", "gurugram")


def passes_filters(job: dict, profile: Profile, f: Filters) -> bool:
    if f.remote_only:
        if not job["remote"]:
            return False
    elif f.locations:
        loc = _norm_loc(job["location"])
        in_place = any(_norm_loc(x).strip() and _norm_loc(x).strip() in loc for x in f.locations)
        if not (in_place or (f.include_remote and job["remote"])):
            return False
    # Skip roles that ask for clearly more experience than the candidate has (1 year of slack).
    need = job.get("min_years")
    if profile.years is not None and need is not None and need > profile.years + 1:
        return False
    return True


def _similarities(profile_text: str, job_texts: list[str]) -> list[float]:
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True,
                              max_features=30000)
        m = vec.fit_transform([profile_text] + job_texts)
        return list(linear_kernel(m[0:1], m[1:])[0])
    except ValueError:  # empty vocabulary
        return [0.0] * len(job_texts)


def _coverage(wanted: list[str], have_lower: set[str]) -> tuple[list[str], list[str]]:
    """Split wanted skills into (matched, missing), comparing case-insensitively."""
    matched = [s for s in wanted if s.lower() in have_lower]
    return matched, [s for s in wanted if s.lower() not in have_lower]


def template_why(matched: list[str], missing: list[str], total_required: int) -> str:
    if total_required == 0:
        return "No specific skills could be read from this posting, so the score uses text similarity only."
    head = f"You match {len(matched)} of {total_required} required skills"
    head += f" ({', '.join(matched[:5])})." if matched else "."
    if missing:
        head += f" Missing: {', '.join(missing[:4])}."
    return head


def rank(profile: Profile, jobs: list[dict], f: Filters, limit: int = 30):
    """Return (results, considered) where considered = jobs left after filters."""
    candidates = [j for j in jobs if passes_filters(j, profile, f)]
    if not candidates:
        return [], 0

    sims = _similarities(profile.text, [f"{j['title']}\n{j['description']}" for j in candidates])
    max_sim = max(sims) or 1.0
    have = {s.lower() for s in profile.skills}
    kws = [k.lower().strip() for k in f.role_keywords if k.strip()]

    results = []
    for job, sim in zip(candidates, sims):
        req_m, req_x = _coverage(job["skills_required"], have)
        pref_m, pref_x = _coverage(job["skills_preferred"], have)

        n_req = len(job["skills_required"])
        sim_n = sim / max_sim  # 1.0 for the most similar job in this batch
        if n_req:
            req_cov = len(req_m) / n_req
            if job["skills_preferred"]:
                pref_cov = len(pref_m) / len(job["skills_preferred"])
                score = 0.50 * req_cov + 0.10 * pref_cov + 0.40 * sim_n
            else:
                score = 0.55 * req_cov + 0.45 * sim_n
        else:
            score = 0.6 * sim_n  # nothing structured to compare, so cap the score
        if kws and any(k in job["title"].lower() for k in kws):
            score += 0.08

        results.append({
            "id": job["id"], "company": job["company"], "title": job["title"],
            "location": job["location"], "remote": job["remote"], "url": job["url"],
            "posted_at": job["posted_at"], "source": job["source"],
            "snippet": (job["description"] or "")[:280].replace("\n", " ").strip(),
            "score": int(round(min(score, 1.0) * 100)),
            "required_matched": req_m, "required_missing": req_x,
            "preferred_matched": pref_m, "preferred_missing": pref_x,
            "why": template_why(req_m, req_x, n_req),
        })

    results.sort(key=lambda r: (-r["score"], -len(r["required_matched"]), r["company"]))
    return results[:limit], len(candidates)