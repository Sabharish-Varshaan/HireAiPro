import uuid

from pydantic import BaseModel

from app.models.enums import ApplicationStatus


class ApplicationCreate(BaseModel):
    job_id: uuid.UUID


class ApplicationOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    student_id: uuid.UUID
    status: ApplicationStatus

    class Config:
        from_attributes = True


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    note: str | None = None
