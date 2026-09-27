import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobStatus, RequirementType


class JobCreate(BaseModel):
    title: str
    description_raw: str | None = None
    location: str | None = None
    employment_type: str | None = None


class JobSkillOut(BaseModel):
    id: uuid.UUID
    skill_id: uuid.UUID | None
    raw_skill_name: str
    requirement_type: RequirementType
    minimum_level: float
    importance: float
    evidence_text: str | None
    extraction_confidence: float
    confirmed: bool
    canonical_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class JobOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    description_raw: str | None
    status: JobStatus
    location: str | None
    employment_type: str | None

    model_config = ConfigDict(from_attributes=True)


class JobWithSkillsOut(JobOut):
    skills: list[JobSkillOut] = []
    organization_name: str | None = None


class JobSkillUpdate(BaseModel):
    id: uuid.UUID | None = None
    skill_id: uuid.UUID | None = None
    raw_skill_name: str
    requirement_type: RequirementType
    minimum_level: float
    importance: float
    delete: bool = False


class ConfirmRequirementsRequest(BaseModel):
    skills: list[JobSkillUpdate]


class ExtractedJobSkill(BaseModel):
    raw_skill_name: str
    requirement_type: Literal["required", "preferred"]
    minimum_level: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    evidence_text: str
    extraction_confidence: float = Field(ge=0, le=1)


class ExtractedJobSkills(BaseModel):
    skills: list[ExtractedJobSkill]
