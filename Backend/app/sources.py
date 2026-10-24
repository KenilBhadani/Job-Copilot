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

RECRUITEE_URL = "https://{slug}.recruitee.com/api/offers/"
WORKABLE_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
SMARTRECRUITERS_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}"
SMARTRECRUITERS_DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}"


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

def normalize_recruitee(company: dict, payload: dict) -> list[dict]:
    out = []
    for j in payload.get("offers", []):
        if j.get("status") not in (None, "published"):
            continue
        loc = j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        desc = "\n".join(p for p in (html_to_text(j.get("description")),
                                     html_to_text(j.get("requirements"))) if p)
        out.append(_job("recruitee", company, j["id"], j.get("title"), loc,
                        bool(j.get("remote")) or _is_remote(loc, j.get("title")),
                        j.get("careers_url"), desc, j.get("published_at") or j.get("created_at")))
    return out


def normalize_workable(company: dict, payload: dict) -> list[dict]:
    out = []
    for j in payload.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        remote = bool(j.get("telecommuting")) or _is_remote(loc, j.get("title"))  # Workable's name for remote
        out.append(_job("workable", company, j.get("shortcode") or j.get("id"), j.get("title"), loc,
                        remote, j.get("url") or j.get("shortlink"), html_to_text(j.get("description")),
                        j.get("published_on") or j.get("created_at")))
    return out


def normalize_smartrecruiters(company: dict, postings: list, details: dict) -> list[dict]:
    """`postings` is the list response (no descriptions); `details` maps id -> detail response."""
    out = []
    for j in postings:
        loc = j.get("location") or {}
        full = loc.get("fullLocation") or ", ".join(
            x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x)
        sections = ((details.get(j["id"]) or {}).get("jobAd") or {}).get("sections") or {}
        desc = "\n".join(html_to_text((sections.get(k) or {}).get("text"))
                         for k in ("jobDescription", "qualifications", "additionalInformation"))
        url = (details.get(j["id"]) or {}).get("postingUrl") or \
            f"https://jobs.smartrecruiters.com/{company['slug']}/{j['id']}"
        out.append(_job("smartrecruiters", company, j["id"], j.get("name"), full,
                        bool(loc.get("remote")) or _is_remote(full, j.get("name")),
                        url, desc.strip(), j.get("releasedDate")))
    return out

_SOURCES = {
    "greenhouse": (GREENHOUSE_URL, normalize_greenhouse),
    "lever": (LEVER_URL, normalize_lever),
    "ashby": (ASHBY_URL, normalize_ashby),
    "recruitee": (RECRUITEE_URL, normalize_recruitee),
    "workable": (WORKABLE_URL, normalize_workable),
}
# SmartRecruiters needs extra calls, so it has its own fetch function below.
SOURCE_NAMES = tuple(_SOURCES) + ("smartrecruiters",)
# ---- fetching ----------------------------------------------------------------------

async def _fetch_smartrecruiters(client, company: dict, with_details: bool,
                                 max_pages: int = 5, max_details: int = 150) -> list[dict]:
    """List postings (100 per page), keep India ones, then fetch each one's description.

    The list has no descriptions, so each India job costs one extra call (capped).
    """
    slug = company["slug"]
    listed: list[dict] = []
    for page in range(max_pages):
        resp = await client.get(SMARTRECRUITERS_URL.format(slug=slug, offset=page * 100))
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        listed += content
        if len(content) < 100 or len(listed) >= data.get("totalFound", 0):
            break
    india = [j for j in listed if ((j.get("location") or {}).get("country") or "").lower() == "in"]

    details: dict = {}
    if with_details:
        sem = asyncio.Semaphore(4)

        async def one(j: dict) -> None:
            async with sem:
                try:
                    r = await client.get(SMARTRECRUITERS_DETAIL_URL.format(slug=slug, id=j["id"]))
                    r.raise_for_status()
                    details[j["id"]] = r.json()
                except Exception:
                    pass  # this job just keeps an empty description

        await asyncio.gather(*(one(j) for j in india[:max_details]))
    return normalize_smartrecruiters(company, india, details)


async def fetch_company(client, company: dict, with_details: bool = True) -> list[dict]:
    source = company["source"]
    if source == "smartrecruiters":
        return await _fetch_smartrecruiters(client, company, with_details)
    if source not in _SOURCES:
        raise ValueError(f"unknown source '{source}' (use {', '.join(SOURCE_NAMES)})")
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