import uuid

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk
from app.models.enums import AssessmentAttemptStatus


class Assessment(Base, UUIDPk, TimestampMixin):
    __tablename__ = "assessments"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    total_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    blueprint: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Recruiter-set delivery options: {duration_minutes, randomize_questions, randomize_options}
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AssessmentSection(Base, UUIDPk, TimestampMixin):
    __tablename__ = "assessment_sections"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id"), index=True
    )
    title: Mapped[str] = mapped_column(String)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class AssessmentQuestion(Base, UUIDPk, TimestampMixin):
    __tablename__ = "assessment_questions"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_sections.id"), nullable=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id")
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[float] = mapped_column(Float, default=1.0)


class AssessmentAttempt(Base, UUIDPk, TimestampMixin):
    __tablename__ = "assessment_attempts"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_profiles.id"), index=True
    )
    status: Mapped[AssessmentAttemptStatus] = mapped_column(
        String, default=AssessmentAttemptStatus.IN_PROGRESS
    )
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Frozen content + server-authoritative clock + persisted per-attempt layout (refresh never reshuffles or resets time)
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assessment_versions.id"), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    question_order: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {section_id: [assessment_question_id]}
    option_orders: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {assessment_question_id: [original option index per displayed slot]}


class AssessmentVersion(Base, UUIDPk, TimestampMixin):
    """Immutable snapshot taken at publish (or at first start for legacy assessments). Attempts grade and render from
    this content only, so later changes to the question bank cannot alter a candidate's assessment."""
    __tablename__ = "assessment_versions"

    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSONB)
    content: Mapped[dict] = mapped_column(JSONB)  # contains answer keys and hidden tests: server-side only
    content_hash: Mapped[str] = mapped_column(String)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class AssessmentAnswer(Base, UUIDPk, TimestampMixin):
    __tablename__ = "assessment_answers"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_attempts.id"), index=True
    )
    assessment_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_questions.id")
    )
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_option_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rubric_evaluation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    marked_for_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
