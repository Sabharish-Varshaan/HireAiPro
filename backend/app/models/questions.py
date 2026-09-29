import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Float, Integer, String, Text
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
    # Stable language ids (python/javascript/cpp); NULL = all supported languages.
    allowed_languages: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    source_type: Mapped[QuestionSourceType] = mapped_column(String)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    visibility: Mapped[Visibility] = mapped_column(String, default=Visibility.COMPANY_PRIVATE)

    knowledge_source_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    status: Mapped[QuestionStatus] = mapped_column(String, default=QuestionStatus.DRAFT)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    validation_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generation_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # Where a company question came from: COMPANY_IMPORT | COMPANY_MANUAL | AI_GENERATED_COMPANY_PRIVATE. Ownership (organization_id + visibility)
    # is separate from usage (assessment_questions), so one private question can serve several of the company's jobs.
    provenance: Mapped[str | None] = mapped_column(String, nullable=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("question_import_batches.id"), nullable=True)
    import_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # external_question_id, explanation, tags, time_limit_seconds, required, max_score


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


class QuestionImportBatch(Base, UUIDPk, TimestampMixin):
    """One upload: parsed and validated rows are held here for the recruiter's review; nothing is a Question until it is confirmed."""
    __tablename__ = "question_import_batches"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id"), nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String)
    format: Mapped[str] = mapped_column(String)  # xlsx | csv | json
    template_version: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="PREVIEW")  # PREVIEW | CONFIRMED | CANCELLED
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)
    rows: Mapped[list] = mapped_column(JSONB, default=list)  # per-row raw values, status, issues, resolved skill
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
