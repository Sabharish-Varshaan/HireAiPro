import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class LearningResource(Base, UUIDPk, TimestampMixin):
    __tablename__ = "learning_resources"

    title: Mapped[str] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    resource_type: Mapped[str] = mapped_column(String, default="article")
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class LearningPath(Base, UUIDPk, TimestampMixin):
    __tablename__ = "learning_paths"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_profiles.id"), index=True
    )
    target_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True
    )
    gap_skill_ids: Mapped[list[str]] = mapped_column(ARRAY(String))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class LearningPathStep(Base, UUIDPk, TimestampMixin):
    __tablename__ = "learning_path_steps"

    learning_path_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_paths.id"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_resources.id"), nullable=True
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(default=False)
