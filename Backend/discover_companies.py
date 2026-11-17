"""Find NEW companies to track, using LangSearch to propose them and the official job
boards to check them.

    python discover_companies.py                       # default queries: one per big Indian city
    python discover_companies.py "ml engineer Pune India" "data engineer Chennai India"

Why two steps: a web search is fuzzy and ignores location, but a company's own job board
is exact. So search only PROPOSES (company, hiring system, slug); the board then says how
many of its jobs are in India. Only companies with India jobs are printed.
Each query uses one call from your LangSearch daily allowance.
"""
import asyncio
import os
import re
import sys

import yaml

from app import config  # importing this loads Backend/.env

SEARCH_URL = "https://api.langsearch.com/v1/web-search"
DOMAINS = ["greenhouse.io", "lever.co", "ashbyhq.com"]
DEFAULT_QUERIES = [f"software engineer {city} India" for city in
                   ("Bengaluru", "Hyderabad", "Pune", "Mumbai", "Gurugram", "Chennai")]

# URL shapes we can turn into (hiring system, slug). Anything else (a company's own domain) is skipped.
URL_PATTERNS = [
    ("greenhouse", re.compile(r"^https?://(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)(?:/|$)")),
    ("lever", re.compile(r"^https?://jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9_.-]+)(?:/|$)")),
    ("ashby", re.compile(r"^https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)(?:/|$)")),
]


def extract_candidates(urls: list[str]) -> set[tuple[str, str]]:
    """{(source, slug)} found in a list of URLs."""
    found = set()
    for url in urls:
        for source, pattern in URL_PATTERNS:
            m = pattern.match(url.strip())
            if m:
                found.add((source, m.group(1)))
    return found


def known_companies(path: str) -> set[tuple[str, str]]:
    with open(path) as f:
        rows = (yaml.safe_load(f) or {}).get("companies", [])
    return {(r["source"], str(r["slug"])) for r in rows}


def display_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


async def search(client, key: str, query: str) -> list[str]:
    resp = await client.post(SEARCH_URL, headers={"Authorization": f"Bearer {key}"},
                             json={"query": query, "count": 10, "freshness": "noLimit",
                                   "includeDomains": DOMAINS})
    if resp.status_code != 200:
        print(f"  search failed (HTTP {resp.status_code}): {query}")  # status only, never the key
        return []
    return [r["url"] for r in resp.json()["data"]["webPages"]["value"]]


async def main(queries: list[str]) -> None:
    import httpx
    from find_slugs import is_india
    from app.sources import fetch_company

    key = os.getenv("LANGSEARCH_API_KEY")
    if not key:
        sys.exit("Add LANGSEARCH_API_KEY to Backend/.env first")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "shortlist-job-matcher/0.1 (personal project)"}) as client:
        urls: list[str] = []
        for q in queries:
            got = await search(client, key, q)
            print(f"{len(got):>2} results: {q}")
            urls += got

        found = extract_candidates(urls)
        known = known_companies(config.COMPANIES_FILE)
        new = sorted(found - known)
        print(f"\n{len(found)} companies found, {len(found) - len(new)} already in companies.yaml, {len(new)} new to check\n")

        sem = asyncio.Semaphore(5)

        async def check(source: str, slug: str):
            async with sem:
                try:
                    jobs = await fetch_company(client, {"name": slug, "source": source, "slug": slug}, with_details=False)
                except Exception:
                    return None
                in_india = sum(1 for j in jobs if is_india(j["location"]))
            return source, slug, len(jobs), in_india

        results = [r for r in await asyncio.gather(*(check(s, sl) for s, sl in new)) if r]

    hits = sorted((r for r in results if r[3] > 0), key=lambda r: -r[3])
    for source, slug, total, in_india in hits:
        print(f"{display_name(slug)}: {source}/{slug}, {total} jobs, {in_india} in India")
        print(f"    paste:  - {{ name: {display_name(slug)}, source: {source}, slug: {slug} }}")
        failed = len(new) - len(results)
    print(f"\n{len(hits)} of {len(new)} new companies have jobs in India. "
          f"{len(results) - len(hits)} have none (skipped). "
          f"{failed} could not be checked (board missing or request failed).")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or DEFAULT_QUERIES))