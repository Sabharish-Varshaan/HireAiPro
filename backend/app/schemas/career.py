import uuid

from pydantic import BaseModel


class CareerStep(BaseModel):
    skill_id: uuid.UUID
    skill_name: str
    rationale: str
    resource_id: uuid.UUID | None = None
    resource_title: str | None = None


class CareerRoadmap(BaseModel):
    target_job_id: uuid.UUID
    gap_skill_ids: list[uuid.UUID]
    steps: list[CareerStep]
    summary: str
