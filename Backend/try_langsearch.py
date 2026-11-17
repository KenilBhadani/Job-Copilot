import os
import httpx
from app import config  # importing this loads Backend/.env

key = os.getenv("LANGSEARCH_API_KEY")
if not key:
    raise SystemExit("Add LANGSEARCH_API_KEY to Backend/.env first")

body = {
    "query": "backend engineer Pune",
    "count": 10,
    "freshness": "noLimit",
    "includeDomains": ["greenhouse.io", "lever.co", "ashbyhq.com"],
}
resp = httpx.post("https://api.langsearch.com/v1/web-search",
                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                  json=body, timeout=30)
if resp.status_code != 200:
    raise SystemExit(f"HTTP {resp.status_code}")   # status only, so the key can't leak

for r in resp.json()["data"]["webPages"]["value"]:
    print(r["name"])
    print("   ", r["url"])
    print("   ", (r.get("snippet") or "")[:120])