import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import ApplicationStatus


class ApplicationCreate(BaseModel):
    job_id: uuid.UUID


class ApplicationOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    student_id: uuid.UUID
    status: ApplicationStatus
    job_title: str | None = None
    organization_name: str | None = None
    student_name: str | None = None
    match_score: float | None = None
    applied_at: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    note: str | None = None
