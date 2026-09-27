import uuid

from pydantic import BaseModel, ConfigDict


class SkillOut(BaseModel):
    id: uuid.UUID
    canonical_name: str
    category: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)
