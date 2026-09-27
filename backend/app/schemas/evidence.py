import uuid

from pydantic import BaseModel

from app.models.enums import EvidenceSourceType


class SkillEvidenceOut(BaseModel):
    id: uuid.UUID
    skill_id: uuid.UUID
    source_type: EvidenceSourceType
    normalized_score: float
    confidence: float
    difficulty: str | None
    scoring_version: str | None

    class Config:
        from_attributes = True


class StudentSkillOut(BaseModel):
    skill_id: uuid.UUID
    estimated_level: float
    confidence: float
    evidence_count: int
    scoring_version: str
    last_evidence_at: str | None

    class Config:
        from_attributes = True
