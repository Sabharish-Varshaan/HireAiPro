import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class CodingSubmission(Base, UUIDPk, TimestampMixin):
    __tablename__ = "coding_submissions"

    assessment_answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_answers.id"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("questions.id"))
    language: Mapped[str] = mapped_column(String)
    source_code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)


class CodingTestResult(Base, UUIDPk, TimestampMixin):
    __tablename__ = "coding_test_results"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coding_submissions.id"), index=True
    )
    test_case_index: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(default=False)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_kb: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge0_token: Mapped[str | None] = mapped_column(String, nullable=True)
    judge0_status: Mapped[str | None] = mapped_column(String, nullable=True)
