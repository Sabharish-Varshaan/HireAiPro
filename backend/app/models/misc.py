import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk
from app.models.enums import ProcessingStatus


class Notification(Base, UUIDPk, TimestampMixin):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    event_type: Mapped[str | None] = mapped_column(String, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    read: Mapped[bool] = mapped_column(default=False)
    link: Mapped[str | None] = mapped_column(String, nullable=True)


class AIRun(Base, UUIDPk, TimestampMixin):
    __tablename__ = "ai_runs"

    task_type: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[ProcessingStatus] = mapped_column(String, default=ProcessingStatus.PENDING)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    schema_valid: Mapped[bool | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class AgentRun(Base, UUIDPk, TimestampMixin):
    __tablename__ = "agent_runs"

    agent_type: Mapped[str] = mapped_column(String, index=True)
    task: Mapped[str] = mapped_column(String)
    status: Mapped[ProcessingStatus] = mapped_column(String, default=ProcessingStatus.PENDING)
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_type: Mapped[str | None] = mapped_column(String, nullable=True)
    context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    used_fallback: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True)


class AuditEvent(Base, UUIDPk, TimestampMixin):
    __tablename__ = "audit_events"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ProcessingJob(Base, UUIDPk, TimestampMixin):
    """Tracks idempotent background job state (JD/resume processing, embeddings, etc.)."""

    __tablename__ = "processing_jobs"

    job_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String)
    status: Mapped[ProcessingStatus] = mapped_column(String, default=ProcessingStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
