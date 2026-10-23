"""Job sources: public job-board endpoints of Greenhouse, Lever and Ashby.

These endpoints are published by the ATS vendors so companies can embed their
listings on their own career pages. Check each vendor's current docs and rate
limits before changing anything here. Never scrape sites that forbid it.

Each normalize_* function is pure (payload in, jobs out) so it can be unit tested.
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


# ---- helpers -----------------------------------------------------------------------

def html_to_text(raw: str | None) -> str:
    """HTML (possibly entity-escaped, as Greenhouse returns it) to plain text with line breaks."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/ul|/ol)\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _is_remote(*parts: str | None) -> bool:
    return any(p and "remote" in p.lower() for p in parts)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):  # Lever uses epoch milliseconds
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    return str(value)


def _job(source: str, company: dict, ext_id, title, location, remote, url, description, posted):
    return {
        "id": f"{source}:{company['slug']}:{ext_id}",
        "company": company["name"],
        "company_key": f"{source}:{company['slug']}",
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "remote": bool(remote),
        "url": url or "",
        "description": description,
        "source": source,
        "posted_at": _iso(posted),
    }


# ---- normalizers -------------------------------------------------------------------

def normalize_greenhouse(company: dict, payload: dict) -> list[dict]:
    out = []
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(_job("greenhouse", company, j["id"], j.get("title"), loc,
                        _is_remote(loc, j.get("title")), j.get("absolute_url"),
                        html_to_text(j.get("content")), j.get("updated_at")))
    return out


def normalize_lever(company: dict, payload: list) -> list[dict]:
    out = []
    for j in payload:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
        for block in j.get("lists") or []:
            parts.append(block.get("text", ""))
            parts.append(html_to_text(block.get("content")))
        parts.append(j.get("additionalPlain") or "")
        out.append(_job("lever", company, j["id"], j.get("text"), loc,
                        _is_remote(loc, j.get("workplaceType")), j.get("hostedUrl"),
                        "\n".join(p for p in parts if p), j.get("createdAt")))
    return out


def normalize_ashby(company: dict, payload: dict) -> list[dict]:
    out = []
    for j in payload.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
        out.append(_job("ashby", company, j["id"], j.get("title"), loc,
                        j.get("isRemote") or _is_remote(loc, j.get("workplaceType")),
                        j.get("jobUrl"), desc, j.get("publishedAt")))
    return out


_SOURCES = {
    "greenhouse": (GREENHOUSE_URL, normalize_greenhouse),
    "lever": (LEVER_URL, normalize_lever),
    "ashby": (ASHBY_URL, normalize_ashby),
}


# ---- fetching ----------------------------------------------------------------------

async def fetch_company(client, company: dict) -> list[dict]:
    source = company["source"]
    if source not in _SOURCES:
        raise ValueError(f"unknown source '{source}' (use greenhouse, lever or ashby)")
    url_tpl, normalize = _SOURCES[source]
    resp = await client.get(url_tpl.format(slug=company["slug"]))
    resp.raise_for_status()
    return normalize(company, resp.json())


async def fetch_all(companies: list[dict], concurrency: int = 4) -> list[dict]:
    """Fetch every company. Returns one report per company: {company, ok, jobs|error}.

    One failing company never blocks the others.
    """
    import httpx  # imported lazily so the pure functions above need no network libs

    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": "shortlist-job-matcher/0.1 (personal project)"}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:

        async def one(company: dict) -> dict:
            async with sem:
                try:
                    jobs = await fetch_company(client, company)
                    return {"company": company, "ok": True, "jobs": jobs}
                except httpx.HTTPStatusError as e:
                    hint = " (check the slug)" if e.response.status_code == 404 else ""
                    return {"company": company, "ok": False,
                            "error": f"HTTP {e.response.status_code}{hint}"}
                except Exception as e:  # network errors, bad JSON, etc.
                    return {"company": company, "ok": False, "error": f"{type(e).__name__}: {e}"}

        return await asyncio.gather(*(one(c) for c in companies))