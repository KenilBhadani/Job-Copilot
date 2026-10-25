import asyncio
from app.agents.gap import analyze_gap
from app.matching import Profile
from app.skills import extract_skills, classify_job_skills, min_years_required

resume = "Backend engineer, 3 years of experience. FastAPI, Python, PostgreSQL, Docker, AWS, RAG."
JD = """Requirements:
- 5+ years of experience with Python and FastAPI
- Kubernetes and Terraform
- Docker and AWS
- Kafka
Nice to have:
- Observability, Go"""

req, pref = classify_job_skills(JD)
job = {"id": "test:1", "title": "Platform Engineer", "company": "Acme", "description": JD,
       "skills_required": req, "skills_preferred": pref, "min_years": min_years_required(JD)}
profile = Profile(text=resume, skills=extract_skills(resume), years=3)

r = asyncio.run(analyze_gap(profile, job))
print(r["verdict"], "| coverage:", round(r["coverage"], 2), "| years short by:", r["years"]["short_by"],
      "| advice from:", r["advice_source"])
print(r["summary"], "\n")
for a in r["advice"]:
    print(f"[{a['priority']}] {a['skill']}  (builds on: {a['builds_on']})")
    print("   why:", a["why"])
    print("   first step:", a["learn_first"])