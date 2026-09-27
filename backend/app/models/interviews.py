import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class Interview(Base, UUIDPk, TimestampMixin):
    __tablename__ = "interviews"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_profiles.id"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    status: Mapped[str] = mapped_column(String, default="IN_PROGRESS")
    max_turns: Mapped[int] = mapped_column(Integer, default=8)


class InterviewTurn(Base, UUIDPk, TimestampMixin):
    __tablename__ = "interview_turns"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id"), index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer)
    target_skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
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
