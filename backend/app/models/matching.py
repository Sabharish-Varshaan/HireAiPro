import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class Match(Base, UUIDPk, TimestampMixin):
    __tablename__ = "matches"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id"), index=True, unique=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_profiles.id"), index=True
    )

    match_score: Mapped[float] = mapped_column(Float)
    required_skill_fit: Mapped[float] = mapped_column(Float)
    preferred_skill_fit: Mapped[float] = mapped_column(Float)
    evidence_confidence: Mapped[float] = mapped_column(Float)
    semantic_relevance: Mapped[float] = mapped_column(Float)

    strong_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    partial_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    missing_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    matching_version: Mapped[str] = mapped_column(String)
