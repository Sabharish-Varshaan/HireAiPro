import uuid

from pydantic import BaseModel, Field


class ResourceRef(BaseModel):
    resource_id: uuid.UUID
    title: str
    provider: str | None = None
    url: str | None = None
    resource_type: str | None = None


class CareerStep(BaseModel):
    skill_id: uuid.UUID
    skill_name: str
    rationale: str
    is_prerequisite: bool = False
    resources: list[ResourceRef] = Field(default_factory=list)


class CareerRoadmap(BaseModel):
    learning_path_id: uuid.UUID | None = None
    target_job_id: uuid.UUID
    gap_skill_ids: list[uuid.UUID]
    steps: list[CareerStep]
    summary: str
