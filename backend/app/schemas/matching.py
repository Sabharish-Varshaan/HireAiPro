import uuid

from pydantic import BaseModel, ConfigDict


class MatchOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    student_id: uuid.UUID
    match_score: float
    required_skill_fit: float
    preferred_skill_fit: float
    evidence_confidence: float
    semantic_relevance: float
    strong_skills: list | None
    partial_skills: list | None
    missing_skills: list | None
    matching_version: str
    weights: dict | None = None

    model_config = ConfigDict(from_attributes=True)
