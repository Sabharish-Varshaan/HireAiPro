"""Job-specific hiring pipeline (docs/HIRING_PIPELINE_ARCHITECTURE.md).

A job owns an ordered list of stages; each application owns one progress row per ENABLED stage. Stage order and unlocking are
deterministic (app/services/pipeline); no model decides workflow or outcomes."""
import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class HiringStage(Base, UUIDPk, TimestampMixin):
    __tablename__ = "hiring_stages"
    __table_args__ = (UniqueConstraint("job_id", "stage_type", name="uq_hiring_stage_job_type"),)

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), index=True)
    stage_type: Mapped[str] = mapped_column(String)  # APTITUDE_ASSESSMENT | TECHNICAL_ASSESSMENT | CODING_ASSESSMENT | TECHNICAL_INTERVIEW | HR_INTERVIEW
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proctored: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String, default="DRAFT")  # DRAFT | READY | PUBLISHED
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id"), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # per-type settings (category mix, languages, competency blueprint, HR categories)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplicationStageProgress(Base, UUIDPk, TimestampMixin):
    __tablename__ = "application_stage_progress"
    __table_args__ = (UniqueConstraint("application_id", "hiring_stage_id", name="uq_stage_progress_app_stage"),)

    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("applications.id"), index=True)
    hiring_stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hiring_stages.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="LOCKED")  # LOCKED | AVAILABLE | IN_PROGRESS | COMPLETED | SKIPPED
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_reference: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {"type": "assessment_attempt" | "interview", "id": "..."}
