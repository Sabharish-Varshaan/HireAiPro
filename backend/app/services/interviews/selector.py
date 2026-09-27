"""Deterministic competency selection for the adaptive interview.

Picks the job-required skill with the highest importance-weighted
uncertainty (low evidence confidence), skipping skills already asked about
too many times or already highly confident. The LLM is only used afterwards
to phrase the actual question for the chosen skill.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RequirementType
from app.models.evidence import StudentSkill
from app.models.interviews import InterviewTurn
from app.models.jobs import JobSkill
from app.models.skills import Skill

HIGH_CONFIDENCE_THRESHOLD = 0.75
MAX_ASKS_PER_SKILL = 2


async def select_next_skill(
    db: AsyncSession, job_id: uuid.UUID, student_id: uuid.UUID, interview_id: uuid.UUID
) -> tuple[uuid.UUID, str, str] | None:
    """Returns (skill_id, skill_name, suggested_difficulty) or None if no
    further competency needs probing."""
    job_skills = (
        await db.scalars(
            select(JobSkill).where(JobSkill.job_id == job_id, JobSkill.confirmed.is_(True), JobSkill.skill_id.is_not(None))
        )
    ).all()
    if not job_skills:
        return None

    asked_counts: dict[uuid.UUID, int] = {}
    turns = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == interview_id))).all()
    for t in turns:
        asked_counts[t.target_skill_id] = asked_counts.get(t.target_skill_id, 0) + 1

    student_skills = {
        s.skill_id: s
        for s in (await db.scalars(select(StudentSkill).where(StudentSkill.student_id == student_id))).all()
    }

    best = None
    best_score = -1.0
    for js in job_skills:
        if asked_counts.get(js.skill_id, 0) >= MAX_ASKS_PER_SKILL:
            continue
        current = student_skills.get(js.skill_id)
        confidence = current.confidence if current else 0.0
        if confidence >= HIGH_CONFIDENCE_THRESHOLD:
            continue
        req_bonus = 1.2 if js.requirement_type == RequirementType.REQUIRED else 1.0
        uncertainty_score = (1 - confidence) * js.importance * req_bonus
        if uncertainty_score > best_score:
            best_score = uncertainty_score
            level = current.estimated_level if current else 0.0
            difficulty = "hard" if level >= 0.7 else "easy" if level <= 0.3 else "medium"
            best = (js.skill_id, difficulty)

    if best is None:
        return None

    skill = await db.get(Skill, best[0])
    return best[0], skill.canonical_name if skill else "Unknown Skill", best[1]
