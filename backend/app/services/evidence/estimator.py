"""skill_scoring_v1 — deterministic skill-level estimation from evidence.

Base weights by evidence source type. RESUME_CLAIM always contributes 0 to
the final estimate; it only exists so recruiters/students can see what was
claimed vs. verified. Weights are renormalized over whichever evidence
categories are actually present for a student+skill pair.
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import EvidenceSourceType
from app.models.evidence import SkillEvidence, StudentSkill

settings = get_settings()

BASE_WEIGHTS: dict[EvidenceSourceType, float] = {
    EvidenceSourceType.CODING: 0.40,
    EvidenceSourceType.MCQ: 0.15,
    EvidenceSourceType.TECHNICAL_ASSESSMENT: 0.15,
    EvidenceSourceType.INTERVIEW: 0.20,
    EvidenceSourceType.PROJECT: 0.10,
    EvidenceSourceType.CERTIFICATE: 0.0,
    EvidenceSourceType.RESUME_CLAIM: 0.0,
}
# MCQ + TECHNICAL_ASSESSMENT together represent the 30% "Structured Assessment"
# bucket from the spec; kept split so mixed MCQ/technical assessments still
# blend sensibly.


def _recency_factor(created_at: dt.datetime) -> float:
    age_days = (dt.datetime.now(dt.timezone.utc) - created_at.replace(tzinfo=dt.timezone.utc)).days
    if age_days <= 30:
        return 1.0
    if age_days <= 180:
        return 0.85
    return 0.65


async def estimate_student_skill(
    db: AsyncSession, student_id: uuid.UUID, skill_id: uuid.UUID
) -> StudentSkill | None:
    evidences = (
        await db.scalars(
            select(SkillEvidence).where(
                SkillEvidence.student_id == student_id,
                SkillEvidence.skill_id == skill_id,
                SkillEvidence.is_deleted.is_(False),
            )
        )
    ).all()

    scorable = [e for e in evidences if BASE_WEIGHTS.get(EvidenceSourceType(e.source_type), 0.0) > 0.0]
    if not scorable:
        stale = await db.scalar(
            select(StudentSkill).where(StudentSkill.student_id == student_id, StudentSkill.skill_id == skill_id)
        )
        if stale:
            await db.delete(stale)
        return None

    present_types = {EvidenceSourceType(e.source_type) for e in scorable}
    weight_sum = sum(BASE_WEIGHTS[t] for t in present_types) or 1.0

    weighted_score = 0.0
    weighted_confidence = 0.0
    for etype in present_types:
        type_evidences = [e for e in scorable if EvidenceSourceType(e.source_type) == etype]
        type_weight = BASE_WEIGHTS[etype] / weight_sum

        # within a type, recency-weighted average, most recent counts more
        num = 0.0
        den = 0.0
        for e in type_evidences:
            rf = _recency_factor(e.created_at)
            num += e.normalized_score * rf
            den += rf
        type_avg = num / den if den else 0.0
        weighted_score += type_weight * type_avg
        weighted_confidence += type_weight * (sum(e.confidence for e in type_evidences) / len(type_evidences))

    diversity_bonus = min(0.15, 0.05 * (len(present_types) - 1))
    count_bonus = min(0.15, 0.03 * len(scorable))
    confidence = max(0.0, min(1.0, weighted_confidence * 0.7 + diversity_bonus + count_bonus))

    existing = await db.scalar(
        select(StudentSkill).where(
            StudentSkill.student_id == student_id, StudentSkill.skill_id == skill_id
        )
    )
    last_evidence_at = max(e.created_at for e in scorable).isoformat()

    if existing:
        existing.estimated_level = weighted_score
        existing.confidence = confidence
        existing.evidence_count = len(scorable)
        existing.scoring_version = settings.SCORING_VERSION
        existing.last_evidence_at = last_evidence_at
        await db.flush()
        return existing

    student_skill = StudentSkill(
        student_id=student_id,
        skill_id=skill_id,
        estimated_level=weighted_score,
        confidence=confidence,
        evidence_count=len(scorable),
        scoring_version=settings.SCORING_VERSION,
        last_evidence_at=last_evidence_at,
    )
    db.add(student_skill)
    await db.flush()
    return student_skill


async def recalculate_all_skills_for_student(
    db: AsyncSession, student_id: uuid.UUID, actor_user_id: uuid.UUID | None = None, reason: str | None = None
) -> list[StudentSkill]:
    from app.services.audit import audit

    skill_ids = set(
        (await db.scalars(select(SkillEvidence.skill_id).where(SkillEvidence.student_id == student_id))).all()
    ) | set((await db.scalars(select(StudentSkill.skill_id).where(StudentSkill.student_id == student_id))).all())
    results = []
    for skill_id in skill_ids:
        result = await estimate_student_skill(db, student_id, skill_id)
        if result:
            results.append(result)
    await audit(
        db, actor_user_id, "skill_profile_recalculated", "student", student_id,
        metadata={"skills": len(results), "reason": reason, "scoring_version": settings.SCORING_VERSION},
    )
    await db.commit()
    return results
