"""Find which job board (Greenhouse, Lever or Ashby) a company uses, and print
ready-to-paste lines for companies.yaml.

Usage (from the Backend folder, venv active):
    python find_slugs.py "Okta" "Glean" "GitLab" "Razorpay"
"""
import asyncio
import re
import sys

from app.sources import SOURCE_NAMES, fetch_company

INDIA = ("india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai",
         "gurugram", "gurgaon", "delhi", "noida", "chennai")


def variants(name: str) -> list[str]:
    """Likely board slugs for a company name, e.g. 'Mistral AI' -> mistralai, mistral-ai ..."""
    clean = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    squashed, dashed = clean.replace(" ", ""), clean.replace(" ", "-")
    out = [squashed, dashed, squashed + "hq", squashed + "inc"]
    return list(dict.fromkeys(v for v in out if v))  # remove duplicates, keep order


async def probe(client, sem, name, source, slug):
    async with sem:
        try:
            jobs = await fetch_company(client, {"name": name, "source": source, "slug": slug})
            return (source, slug, jobs) if jobs else None
        except Exception:
            return None  # 404 or network error means "not this board"


async def main(names: list[str]) -> None:
    import httpx

    sem = asyncio.Semaphore(6)
    headers = {"User-Agent": "shortlist-job-matcher/0.1 (personal project)"}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        for name in names:
            tasks = [probe(client, sem, name, src, slug)
                     for src in SOURCE_NAMES for slug in variants(name)]
            hits = [h for h in await asyncio.gather(*tasks) if h]
            if not hits:
                print(f"\n{name}: no board found. Open its careers page and check the URL.")
                continue
            print(f"\n{name}:")
            for source, slug, jobs in hits:
                in_india = sum(1 for j in jobs if any(k in j["location"].lower() for k in INDIA))
                print(f"  {source}/{slug}: {len(jobs)} jobs, {in_india} in India")
                print(f"    first job: {jobs[0]['title']} -> {jobs[0]['url']}")
                print(f"    paste:  - {{ name: {name}, source: {source}, slug: {slug} }}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: python find_slugs.py "Company One" "Company Two"')
    asyncio.run(main(sys.argv[1:]))