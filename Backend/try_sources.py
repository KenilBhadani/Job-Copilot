import asyncio
from app.sources import fetch_all, normalize_greenhouse

# Test 1: offline, using fake data in Greenhouse's format (no internet needed)
fake = {"jobs": [{"id": 1, "title": "ML Engineer", "absolute_url": "https://example.com/1",
                  "location": {"name": "Remote, India"},
                  "content": "&lt;p&gt;Need Python&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Docker&lt;/li&gt;&lt;/ul&gt;"}]}
job = normalize_greenhouse({"name": "Acme", "slug": "acme"}, fake)[0]
print(job["id"], "| remote:", job["remote"])
print(job["description"])

# Test 2: live, one real company
companies = [{"name": "Anthropic", "source": "greenhouse", "slug": "anthropic"}]
r = asyncio.run(fetch_all(companies))[0]
if r["ok"]:
    print(len(r["jobs"]), "jobs fetched")
    j = r["jobs"][0]
    print(j["title"], "|", j["location"], "|", j["url"])
else:
    print("failed:", r["error"])