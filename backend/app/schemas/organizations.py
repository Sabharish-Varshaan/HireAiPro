import uuid

from pydantic import BaseModel, ConfigDict


class OrganizationCreate(BaseModel):
    name: str
    website: str | None = None
    industry: str | None = None


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    website: str | None
    industry: str | None

    model_config = ConfigDict(from_attributes=True)
