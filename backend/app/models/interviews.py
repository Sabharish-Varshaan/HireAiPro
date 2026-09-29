import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class InterviewTemplate(Base, UUIDPk, TimestampMixin):
    """Interview blueprint for a job, prepared at authoring time: competencies, coverage rules and a validated question pool."""
    __tablename__ = "interview_templates"
    __table_args__ = (UniqueConstraint("job_id", "stage_type", name="uq_interview_template_job_stage"),)

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), index=True)
    stage_type: Mapped[str] = mapped_column(String, default="TECHNICAL_INTERVIEW", server_default="TECHNICAL_INTERVIEW")  # TECHNICAL_INTERVIEW | HR_INTERVIEW
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="PREPARING")  # PREPARING | READY | FAILED
    config: Mapped[dict] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class InterviewPoolQuestion(Base, UUIDPk, TimestampMixin):
    __tablename__ = "interview_pool_questions"

    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("interview_templates.id"), index=True)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), index=True, nullable=True)  # NULL for HR (category instead)
    difficulty: Mapped[str] = mapped_column(String)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)  # technical: conceptual | scenario | debugging | tradeoff | clarify; HR: behavioural
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # HR topic
    layer: Mapped[int | None] = mapped_column(Integer, nullable=True)  # depth layer 1..5 for technical drilling
    question_text: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String)  # question_bank | generated
    source_question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=True)
    source_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str] = mapped_column(String, index=True)


class Interview(Base, UUIDPk, TimestampMixin):
    __tablename__ = "interviews"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_profiles.id"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    stage_type: Mapped[str] = mapped_column(String, default="TECHNICAL_INTERVIEW", server_default="TECHNICAL_INTERVIEW", index=True)
    hiring_stage_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hiring_stages.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="IN_PROGRESS")
    max_turns: Mapped[int] = mapped_column(Integer, default=8)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # session plan fixed at start: ranked competencies + template version


class InterviewTurn(Base, UUIDPk, TimestampMixin):
    __tablename__ = "interview_turns"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id"), index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer)
    target_skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), nullable=True)  # NULL for HR turns
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # HR topic
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    layer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_text: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String, default="medium")
    reason_for_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    rubric_evaluation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    answer_source: Mapped[str | None] = mapped_column(String, nullable=True)
    transcript_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # per-stage milliseconds (docs/INTERVIEW_LATENCY.md)
    pool_question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("interview_pool_questions.id"), nullable=True)
