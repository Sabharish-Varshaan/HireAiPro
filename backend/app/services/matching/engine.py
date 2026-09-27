"""matching_v1 — fully deterministic candidate-job matching.

Never calls an LLM to produce the score itself; the LLM is only used
downstream (in the API layer) to phrase an explanation of numbers computed
here.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.applications import Application
from app.models.enums import RequirementType
from app.models.evidence import StudentSkill
from app.models.jobs import JobSkill
from app.models.matching import Match
from app.models.skills import Skill

settings = get_settings()

WEIGHTS = {
    "required": 0.60,
    "preferred": 0.20,
    "evidence_confidence": 0.15,
    "semantic_relevance": 0.05,
}


def skill_fit(student_level: float, required_level: float) -> float:
    if required_level <= 0:
        return 1.0
    return min(student_level / required_level, 1.0)


async def compute_match_for_application(db: AsyncSession, application_id: uuid.UUID) -> Match:
    application = await db.get(Application, application_id)
    if application is None:
        raise ValueError("Application not found")

    job_skills = (
        await db.scalars(
            select(JobSkill).where(JobSkill.job_id == application.job_id, JobSkill.confirmed.is_(True))
        )
    ).all()

    student_skills = {
        s.skill_id: s
        for s in (
            await db.scalars(
                select(StudentSkill).where(StudentSkill.student_id == application.student_id)
            )
        ).all()
    }

    required = [js for js in job_skills if js.requirement_type == RequirementType.REQUIRED and js.skill_id]
    preferred = [js for js in job_skills if js.requirement_type == RequirementType.PREFERRED and js.skill_id]

    strong_skills, partial_skills, missing_skills = [], [], []

    def score_group(group: list[JobSkill]) -> float:
        if not group:
            return 1.0
        total = 0.0
        for js in group:
            student_skill = student_skills.get(js.skill_id)
            level = student_skill.estimated_level if student_skill else 0.0
            fit = skill_fit(level, js.minimum_level)
            total += fit * js.importance
            skill_name = js.raw_skill_name
            entry = {"skill_id": str(js.skill_id), "skill_name": skill_name, "fit": round(fit, 3)}
            if fit >= 0.8:
                strong_skills.append(entry)
            elif fit >= 0.4:
                partial_skills.append(entry)
            else:
                missing_skills.append(entry)
        importance_sum = sum(js.importance for js in group) or 1.0
        return total / importance_sum

    required_fit = score_group(required)
    preferred_fit = score_group(preferred)

    all_job_skill_ids = [js.skill_id for js in job_skills if js.skill_id]
    matched_skills = [student_skills[sid] for sid in all_job_skill_ids if sid in student_skills]
    evidence_confidence = (
        sum(s.confidence for s in matched_skills) / len(matched_skills) if matched_skills else 0.0
    )

    # Semantic relevance: fraction of job skills for which the student has ANY
    # evidence at all (even low level) — a coarse deterministic proxy that
    # rewards breadth of exposure beyond the exact minimum-level bar.
    semantic_relevance = (
        len([sid for sid in all_job_skill_ids if sid in student_skills]) / len(all_job_skill_ids)
        if all_job_skill_ids
        else 0.0
    )

    match_score = (
        WEIGHTS["required"] * required_fit
        + WEIGHTS["preferred"] * preferred_fit
        + WEIGHTS["evidence_confidence"] * evidence_confidence
        + WEIGHTS["semantic_relevance"] * semantic_relevance
    )

    existing = await db.scalar(select(Match).where(Match.application_id == application.id))
    if existing:
        match = existing
    else:
        match = Match(application_id=application.id, job_id=application.job_id, student_id=application.student_id)
        db.add(match)

    match.match_score = round(match_score, 4)
    match.required_skill_fit = round(required_fit, 4)
    match.preferred_skill_fit = round(preferred_fit, 4)
    match.evidence_confidence = round(evidence_confidence, 4)
    match.semantic_relevance = round(semantic_relevance, 4)
    match.strong_skills = strong_skills
    match.partial_skills = partial_skills
    match.missing_skills = missing_skills
    match.matching_version = settings.MATCHING_VERSION

    await db.commit()
    await db.refresh(match)
    return match
