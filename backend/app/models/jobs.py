import uuid

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk
from app.models.enums import JobStatus, RequirementType


class Job(Base, UUIDPk, TimestampMixin):
    __tablename__ = "jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    title: Mapped[str] = mapped_column(String)
    description_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    jd_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    status: Mapped[JobStatus] = mapped_column(String, default=JobStatus.DRAFT)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # Posting details (docs/JOB_POSTING.md). employment_type/location predate this and are reused: employment_type now holds a machine
    # value (FULL_TIME ...), `location` is a derived display string. Money is stored as absolute amounts in a generic currency/period model.
    work_mode: Mapped[str | None] = mapped_column(String, nullable=True)  # ONSITE | HYBRID | REMOTE (null = recruiter has not chosen)
    location_city: Mapped[str | None] = mapped_column(String, nullable=True)
    location_state: Mapped[str | None] = mapped_column(String, nullable=True)
    location_country: Mapped[str | None] = mapped_column(String, nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String, nullable=True)  # FRESHER | EXPERIENCED
    experience_min_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_max_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number_of_openings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compensation_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    compensation_min: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    compensation_max: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    compensation_period: Mapped[str | None] = mapped_column(String, nullable=True)  # YEAR | MONTH | HOUR | FIXED
    compensation_type: Mapped[str | None] = mapped_column(String, nullable=True)  # SALARY | STIPEND | CTC | HOURLY | UNPAID
    internship_duration_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    internship_duration_unit: Mapped[str | None] = mapped_column(String, nullable=True)  # WEEK | MONTH
    conversion_guaranteed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    conversion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_time_compensation_min: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)  # annual, compensation_currency
    full_time_compensation_max: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    @property
    def display(self) -> dict:
        from app.services.jobs.posting import display

        return display(self)

    # Distribution (docs/OPPORTUNITIES.md): OPEN_MARKET jobs are visible to every student; INSTITUTION jobs only after the
    # target institution's placement officer approves them, and then only to students matching `eligibility`.
    distribution_type: Mapped[str] = mapped_column(String, default="OPEN_MARKET", server_default="OPEN_MARKET")
    target_institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=True, index=True)
    institution_approval: Mapped[str] = mapped_column(String, default="NOT_REQUIRED", server_default="NOT_REQUIRED")  # NOT_REQUIRED|PENDING|APPROVED|REJECTED
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assessment_target_questions: Mapped[int | None] = mapped_column(nullable=True)  # recruiter's requested assessment size
    eligibility: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {department_ids, cohort_ids, graduation_years}; empty/absent = all


class JobSkill(Base, UUIDPk, TimestampMixin):
    __tablename__ = "job_skills"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), index=True
    )
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), nullable=True
    )
    raw_skill_name: Mapped[str] = mapped_column(String)
    requirement_type: Mapped[RequirementType] = mapped_column(String)
    minimum_level: Mapped[float] = mapped_column(Float)
    importance: Mapped[float] = mapped_column(Float)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed: Mapped[bool] = mapped_column(default=False)
