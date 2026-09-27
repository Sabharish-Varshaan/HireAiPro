import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import EvidenceSourceType


class SkillEvidenceOut(BaseModel):
    id: uuid.UUID
    skill_id: uuid.UUID
    skill_name: str | None = None
    source_type: EvidenceSourceType
    normalized_score: float
    confidence: float
    difficulty: str | None
    scoring_version: str | None
    rubric_version: str | None = None
    created_at: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StudentSkillOut(BaseModel):
    skill_id: uuid.UUID
    skill_name: str | None = None
    estimated_level: float
    confidence: float
    evidence_count: int
    scoring_version: str
    last_evidence_at: str | None

    model_config = ConfigDict(from_attributes=True)
