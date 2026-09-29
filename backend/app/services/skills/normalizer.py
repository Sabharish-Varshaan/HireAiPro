"""Deterministic-first skill normalization.

Resolution order: exact canonical name -> alias table -> fuzzy match ->
(optionally) AI disambiguation for genuinely ambiguous cases. The LLM is
never allowed to invent a permanent canonical skill id; it may only pick
among candidates already in the taxonomy.
"""

import difflib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skills import Skill, SkillAlias


def _normalize_text(name: str) -> str:
    """Case/punctuation-insensitive key that keeps the meaning of '+' and '#':
    "C++" -> "cpp", "C#" -> "csharp", "C" -> "c". Stripping them made all three
    collide on "c", so a resume's "C++" resolved to C# (found 2026-09-29)."""
    n = name.lower().replace("++", "pp").replace("+", "plus").replace("#", "sharp")
    return re.sub(r"[^a-z0-9]+", "", n)


async def _load_index(db: AsyncSession) -> tuple[dict[str, uuid.UUID], dict[str, str]]:
    skills = (await db.scalars(select(Skill))).all()
    aliases = (await db.scalars(select(SkillAlias))).all()

    exact: dict[str, uuid.UUID] = {}
    display: dict[str, str] = {}
    for s in skills:
        key = _normalize_text(s.canonical_name)
        exact[key] = s.id
        display[key] = s.canonical_name
    for a in aliases:
        exact.setdefault(a.alias_normalized, a.skill_id)
    return exact, display


async def normalize_skill_name(db: AsyncSession, raw_name: str) -> tuple[uuid.UUID | None, float]:
    """Returns (skill_id or None, confidence)."""
    if not raw_name or not raw_name.strip():
        return None, 0.0

    norm = _normalize_text(raw_name)
    exact, _ = await _load_index(db)

    if norm in exact:
        return exact[norm], 1.0

    # fuzzy fallback over known keys
    best_key = None
    best_ratio = 0.0
    for key in exact:
        ratio = difflib.SequenceMatcher(None, norm, key).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_key = key

    if best_key and best_ratio >= 0.86:
        return exact[best_key], best_ratio

    return None, best_ratio


async def normalize_many(db: AsyncSession, raw_names: list[str]) -> dict[str, tuple[uuid.UUID | None, float]]:
    result = {}
    for name in raw_names:
        result[name] = await normalize_skill_name(db, name)
    return result
