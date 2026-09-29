import uuid

from sqlalchemy import Float, ForeignKey, String, Text
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
    # Distribution (docs/OPPORTUNITIES.md): OPEN_MARKET jobs are visible to every student; INSTITUTION jobs only after the
    # target institution's placement officer approves them, and then only to students matching `eligibility`.
    distribution_type: Mapped[str] = mapped_column(String, default="OPEN_MARKET", server_default="OPEN_MARKET")
    target_institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=True, index=True)
    institution_approval: Mapped[str] = mapped_column(String, default="NOT_REQUIRED", server_default="NOT_REQUIRED")  # NOT_REQUIRED|PENDING|APPROVED|REJECTED
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
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
