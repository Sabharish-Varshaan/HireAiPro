import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import EvidenceSourceType
from app.models.evidence import SkillEvidence

settings = get_settings()


async def record_evidence(
    db: AsyncSession,
    student_id: uuid.UUID,
    skill_id: uuid.UUID,
    source_type: EvidenceSourceType,
    normalized_score: float,
    *,
    source_id: uuid.UUID | None = None,
    raw_score: float | None = None,
    difficulty: str | None = None,
    confidence: float = 0.5,
    model_id: str | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    rubric_version: str | None = None,
) -> SkillEvidence:
    evidence = SkillEvidence(
        student_id=student_id,
        skill_id=skill_id,
        source_type=source_type,
        source_id=source_id,
        raw_score=raw_score,
        normalized_score=max(0.0, min(1.0, normalized_score)),
        difficulty=difficulty,
        confidence=max(0.0, min(1.0, confidence)),
        model_id=model_id,
        model_version=model_version,
        prompt_version=prompt_version,
        rubric_version=rubric_version,
        scoring_version=settings.SCORING_VERSION,
    )
    db.add(evidence)
    await db.flush()
    return evidence
