from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config, db, llm, resume, sources
from .matching import Filters, rank
from .profile import build_profile
from .skills import classify_job_skills, min_years_required


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()  # create the jobs table on startup if it doesn't exist
    yield


app = FastAPI(title="Shortlist API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_methods=["*"], allow_headers=["*"])


class MatchRequest(BaseModel):
    resume_text: str = ""
    skills: list[str] | None = None            # set when the user edits the skill chips
    experience_years: float | None = Field(default=None, ge=0, le=50)
    locations: list[str] = []
    # include_remote: bool = True
    remote_only: bool = False
    role_keywords: list[str] = []
    limit: int = Field(default=30, ge=1, le=100)
    use_llm: bool = True


def _enrich(job: dict) -> dict:
    """Attach the skills and years we read from the job text."""
    req, pref = classify_job_skills(job["description"])
    job["skills_required"], job["skills_preferred"] = req, pref
    job["min_years"] = min_years_required(job["description"])
    return job


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.available()}


@app.get("/api/stats")
def stats():
    return {**db.stats(), "llm": llm.available()}


@app.post("/api/sync")
async def sync():
    """Pull the latest postings for every company in companies.yaml."""
    with open(config.COMPANIES_FILE) as f:
        companies = (yaml.safe_load(f) or {}).get("companies", [])
    reports = await sources.fetch_all(companies)
    summary = []
    for r in reports:
        c = r["company"]
        if r["ok"]:
            jobs = [_enrich(j) for j in r["jobs"]]
            db.replace_company_jobs(f"{c['source']}:{c['slug']}", jobs)  # failures never wipe old data
            summary.append({"company": c["name"], "ok": True, "jobs": len(jobs)})
        else:
            summary.append({"company": c["name"], "ok": False, "error": r["error"]})
    return {"report": summary, **db.stats()}


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "File is larger than 5 MB.")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF, or paste your resume as text.")
    text = await asyncio.to_thread(resume.pdf_to_text, data)
    if len(text) < 30:
        raise HTTPException(422, "No text found in this PDF. It may be a scanned image; paste the text instead.")
    return {"text": text}


@app.post("/api/match")
async def match(req: MatchRequest):
    text = req.resume_text.strip()
    if len(text) < 30 and not req.skills:
        raise HTTPException(400, "Paste your resume, or at least a few lines about your skills.")

    profile = await build_profile(text, req.skills, req.experience_years, req.use_llm)
    jobs = db.all_jobs()
    out_profile = {"skills": profile.skills, "years": profile.years, "headline": profile.headline}
    if not jobs:
        return {"profile": out_profile, "results": [], "total_jobs": 0, "considered": 0}

    filters = Filters(locations=[l for l in req.locations if l.strip()],
                      remote_only=req.remote_only,
                      role_keywords=req.role_keywords)
    results, considered = rank(profile, jobs, filters, req.limit)

    if req.use_llm and llm.available():  # better "why" for the top few only, to keep it fast
        top = results[:5]
        texts = await asyncio.gather(*(asyncio.to_thread(llm.explain_match, profile.headline, r) for r in top))
        for r, t in zip(top, texts):
            if t:
                r["why"] = t

    return {"profile": out_profile, "results": results, "total_jobs": len(jobs), "considered": considered}