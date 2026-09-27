import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import EvidenceSourceType
from app.models.evidence import SkillEvidence

settings = get_settings()


def evidence_key(source_type: EvidenceSourceType, source_id: uuid.UUID | None, skill_id: uuid.UUID) -> str:
    return f"{source_type.value}:{source_id}:{skill_id}"


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
    idempotency_key: str | None = None,
) -> SkillEvidence:
    """One evidence row per (source event, skill). Re-recording the same event
    updates that row in place — a retried task or re-submitted attempt can
    never double-count evidence."""
    key = idempotency_key or evidence_key(source_type, source_id, skill_id)
    existing = await db.scalar(select(SkillEvidence).where(SkillEvidence.idempotency_key == key))
    ev = existing or SkillEvidence(student_id=student_id, skill_id=skill_id, source_type=source_type, idempotency_key=key)
    ev.source_id = source_id
    ev.raw_score = raw_score
    ev.normalized_score = max(0.0, min(1.0, normalized_score))
    ev.difficulty = difficulty
    ev.confidence = max(0.0, min(1.0, confidence))
    ev.model_id = model_id
    ev.model_version = model_version
    ev.prompt_version = prompt_version
    ev.rubric_version = rubric_version
    ev.scoring_version = settings.SCORING_VERSION
    ev.is_deleted = False
    if existing is None:
        db.add(ev)
    await db.flush()
    return ev
