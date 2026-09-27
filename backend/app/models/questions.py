import uuid

from sqlalchemy import ForeignKey, Float, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk
from app.models.enums import QuestionSourceType, QuestionStatus, QuestionType, Visibility


class QuestionBank(Base, UUIDPk, TimestampMixin):
    __tablename__ = "question_banks"

    name: Mapped[str] = mapped_column(String)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    visibility: Mapped[Visibility] = mapped_column(String, default=Visibility.COMPANY_PRIVATE)


class Question(Base, UUIDPk, TimestampMixin):
    __tablename__ = "questions"

    question_bank_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_banks.id"), nullable=True, index=True
    )
    question_text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[QuestionType] = mapped_column(String)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), index=True
    )
    subskill_text: Mapped[str | None] = mapped_column(String, nullable=True)
    difficulty: Mapped[str] = mapped_column(String, default="medium")

    options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    correct_option_index: Mapped[int | None] = mapped_column(nullable=True)

    expected_concepts: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    rubric: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    starter_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_cases: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    source_type: Mapped[QuestionSourceType] = mapped_column(String)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    visibility: Mapped[Visibility] = mapped_column(String, default=Visibility.COMPANY_PRIVATE)

    knowledge_source_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    status: Mapped[QuestionStatus] = mapped_column(String, default=QuestionStatus.DRAFT)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)


class QuestionSkill(Base, UUIDPk, TimestampMixin):
    __tablename__ = "question_skills"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id"), index=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class QuestionSource(Base, UUIDPk, TimestampMixin):
    __tablename__ = "question_sources"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id"), index=True
    )
    knowledge_chunk_id: Mapped[str] = mapped_column(String)
    citation: Mapped[str | None] = mapped_column(Text, nullable=True)
