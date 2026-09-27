import uuid

from pydantic import BaseModel


class SkillOut(BaseModel):
    id: uuid.UUID
    canonical_name: str
    category: str
    description: str | None = None

    class Config:
        from_attributes = True
