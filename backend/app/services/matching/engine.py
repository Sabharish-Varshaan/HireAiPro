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

    if not job_skills:
        raise ValueError("Job has no confirmed requirements; matching needs recruiter-confirmed skills")

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

    semantic_relevance = await _semantic_relevance(db, application.job_id, student_skills)

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

    from app.services.audit import audit

    await audit(db, None, "match_recalculated", "application", application.id,
                metadata={"match_score": match.match_score, "matching_version": match.matching_version})
    await db.commit()
    await db.refresh(match)
    return match


async def _semantic_relevance(db: AsyncSession, job_id: uuid.UUID, student_skills: dict) -> float:
    """Cosine similarity (BGE-M3, normalized) between the job profile (title +
    confirmed skills) and the student's *verified* skill profile. Resume claims
    are excluded because only StudentSkill rows (scored evidence) are used.
    Deterministic for fixed inputs; clipped to [0, 1]."""
    from app.models.jobs import Job
    from app.services.ai_gateway.embeddings import get_embedding_service

    if not student_skills:
        return 0.0
    job = await db.get(Job, job_id)
    job_skill_ids = (await db.scalars(select(JobSkill.skill_id).where(JobSkill.job_id == job_id, JobSkill.confirmed.is_(True)))).all()
    names = {s.id: s.canonical_name for s in (await db.scalars(
        select(Skill).where(Skill.id.in_(set(job_skill_ids) | set(student_skills))))).all()}
    job_text = f"{job.title}. Skills: " + ", ".join(names.get(i, "") for i in job_skill_ids if i)
    student_text = "Demonstrated skills: " + ", ".join(
        f"{names.get(sid, '')} ({'strong' if ss.estimated_level >= 0.7 else 'working' if ss.estimated_level >= 0.4 else 'basic'})"
        for sid, ss in sorted(student_skills.items(), key=lambda kv: -kv[1].estimated_level)
    )
    a, b = get_embedding_service().embed([job_text, student_text])
    return max(0.0, min(1.0, float(sum(x * y for x, y in zip(a, b)))))
