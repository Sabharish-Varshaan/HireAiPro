import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class StudentProfileOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    headline: str | None
    bio: str | None
    location: str | None
    resume_parse_status: str

    model_config = ConfigDict(from_attributes=True)


class StudentProfileUpdate(BaseModel):
    headline: str | None = None
    bio: str | None = None
    location: str | None = None


class EducationCreate(BaseModel):
    institution_name: str
    degree: str | None = None
    field_of_study: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    gpa: float | None = None


class ExperienceCreate(BaseModel):
    company_name: str
    title: str
    description: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class ProjectCreate(BaseModel):
    title: str
    description: str | None = None
    url: str | None = None
    claimed_skill_names: list[str] | None = None


class CertificationCreate(BaseModel):
    name: str
    issuer: str | None = None
    issued_date: dt.date | None = None
    credential_url: str | None = None
