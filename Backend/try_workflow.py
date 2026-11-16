import asyncio
import time

from app.agents.workflow import RunManager
from app.skills import classify_job_skills, extract_skills

resume = """Asha Rao
Experience
- Built REST APIs in Python and FastAPI serving 12 internal teams
- Reduced report time from 40 minutes to 6 minutes by adding Redis caching
- Deployed services with Docker on AWS and wrote GitHub Actions pipelines
- Built a RAG chatbot using LangChain and pgvector for support documents
- Wrote unit tests with pytest and reviewed teammates' pull requests
"""
JD = """Requirements:
- 5+ years of experience with Python and FastAPI
- RAG and LLMs
- Docker and AWS
- Kubernetes
Nice to have:
- Redis"""

req, pref = classify_job_skills(JD)
job = {"id": "test:1", "title": "AI Engineer", "company": "Acme", "description": JD,
       "skills_required": req, "skills_preferred": pref, "min_years": 5}


async def main():
    mgr = RunManager()

    t0 = time.perf_counter()
    out = await mgr.start(job, resume, extract_skills(resume), years=3)
    wall = time.perf_counter() - t0
    print("status:", out["status"])
    if out["status"] != "awaiting_approval":
        print("UNEXPECTED RESULT:", out)
        return
    for e in out["trace"]:
        print(f"  {e['node']:9}{e['ms']:>7} ms   {e['note']}")
    total = sum(e["ms"] for e in out["trace"])
    print(f"  wall time {wall*1000:.0f} ms vs sum of node times {total} ms (wall < sum means they overlapped)")

    rv = out["review"]
    print("\nHEADLINE:", rv["headline"])
    for b in rv["bullets"]:
        print(f"  [{b['id']}] {b['status']:13} {b['final']}")

    t1 = time.perf_counter()
    done = await mgr.decide(out["run_id"], {"action": "approve", "edits": {"2": "Cut report time from 40 to 6 minutes with Redis caching"}})
    print(f"\nafter approval ({(time.perf_counter()-t1)*1000:.0f} ms): {done['status']}")
    print(done["final"]["text"])
    print("sources:", [b["source"] for b in done["final"]["bullets"]])

    try:
        await mgr.decide(out["run_id"], {"action": "approve"})
    except KeyError:
        print("\nA second approval of the same run is refused, as it should be.")

asyncio.run(main())