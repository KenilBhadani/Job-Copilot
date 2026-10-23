"""Build a Profile from resume text (and/or user-edited skills)."""
from __future__ import annotations

import asyncio

from . import llm
from .matching import Profile
from .skills import ALIAS_TO_SKILL, canonicalize, extract_skills, years_of_experience


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for s in items:
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


async def build_profile(text: str, skills_override: list[str] | None = None,
                        years_override: float | None = None, use_llm: bool = True) -> Profile:
    skills = extract_skills(text)
    years = years_of_experience(text)
    headline = None

    if use_llm and llm.available() and len(text) >= 30:
        parsed = await asyncio.to_thread(llm.parse_profile, text)
        if parsed:
            headline = parsed.get("headline")
            if isinstance(parsed.get("years_experience"), (int, float)):
                years = float(parsed["years_experience"])
            for s in parsed.get("skills") or []:
                if isinstance(s, str) and s.strip().lower() in ALIAS_TO_SKILL:
                    skills.append(canonicalize(s))

    if skills_override is not None:  # the user edited the chips: their list wins
        skills = [canonicalize(s) for s in skills_override]
    if years_override is not None:
        years = years_override
    return Profile(text=text, skills=_dedupe(skills), years=years, headline=headline)