import asyncio
from app.agents.tailor import tailor_resume
from app.skills import extract_skills, classify_job_skills

resume = """Asha Rao
Experience
- Built REST APIs in Python and FastAPI serving 12 internal teams
- Reduced report time from 40 minutes to 6 minutes by adding Redis caching
- Deployed services with Docker on AWS and wrote GitHub Actions pipelines
- Built a RAG chatbot using LangChain and pgvector for support documents
- Wrote unit tests with pytest and reviewed teammates' pull requests
"""
JD = """Requirements:
- Python and FastAPI
- RAG and LLMs
- Docker and AWS
- Kubernetes
Nice to have:
- Redis"""

req, pref = classify_job_skills(JD)
job = {"id": "test:1", "title": "AI Engineer", "company": "Acme", "description": JD,
       "skills_required": req, "skills_preferred": pref, "min_years": None}

r = asyncio.run(tailor_resume(resume, job, extract_skills(resume)))
print("checked_by:", r["checked_by"], "| attempts:", r["attempts"], "| stats:", r["stats"])
if r["note"]:
    print("note:", r["note"])
for b in r["bullets"]:
    print(f"\n[{b['id']}] {b['status'].upper()}")
    print("   original:", b["original"])
    if b["status"] != "unchanged":
        print("   final   :", b["final"])
    if b["status"] == "kept_original":
        print("   rejected:", b["rejected_rewrite"])
        print("   why     :", b["problems"][0])
print("\nSkills now visible for this job:", r["skills_surfaced"])
print("Job wants but you lack:", [s for s in job["skills_required"] if s not in r["skills_surfaced"]])