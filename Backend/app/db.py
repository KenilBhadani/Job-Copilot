"""SQLite job store. Phase 2 can swap this for Postgres + pgvector behind the same functions."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  company_key TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT,
  remote INTEGER DEFAULT 0,
  url TEXT,
  description TEXT,
  source TEXT,
  posted_at TEXT,
  skills_required TEXT,
  skills_preferred TEXT,
  min_years INTEGER,
  fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_key);
"""


@contextmanager
def connect(path: str | None = None):
    path = path or config.DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: str | None = None) -> None:
    with connect(path) as c:
        c.executescript(SCHEMA)


def replace_company_jobs(company_key: str, jobs: list[dict], path: str | None = None) -> None:
    """Replace one company's jobs with the latest fetch (closed postings disappear)."""
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as c:
        c.execute("DELETE FROM jobs WHERE company_key = ?", (company_key,))
        c.executemany(
            """INSERT OR REPLACE INTO jobs
               (id, company, company_key, title, location, remote, url, description, source,
                posted_at, skills_required, skills_preferred, min_years, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(j["id"], j["company"], j["company_key"], j["title"], j["location"], int(j["remote"]),
              j["url"], j["description"], j["source"], j["posted_at"],
              json.dumps(j["skills_required"]), json.dumps(j["skills_preferred"]),
              j["min_years"], now) for j in jobs],
        )


def all_jobs(path: str | None = None) -> list[dict]:
    with connect(path) as c:
        rows = c.execute("SELECT * FROM jobs").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["remote"] = bool(d["remote"])
        d["skills_required"] = json.loads(d["skills_required"] or "[]")
        d["skills_preferred"] = json.loads(d["skills_preferred"] or "[]")
        out.append(d)
    return out


def stats(path: str | None = None) -> dict:
    with connect(path) as c:
        n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        comps = c.execute("SELECT COUNT(DISTINCT company_key) FROM jobs").fetchone()[0]
        last = c.execute("SELECT MAX(fetched_at) FROM jobs").fetchone()[0]
    return {"jobs": n, "companies": comps, "last_sync": last}