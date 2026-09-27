import uuid

from pydantic import BaseModel


class OrganizationCreate(BaseModel):
    name: str
    website: str | None = None
    industry: str | None = None


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    website: str | None
    industry: str | None

    class Config:
        from_attributes = True
