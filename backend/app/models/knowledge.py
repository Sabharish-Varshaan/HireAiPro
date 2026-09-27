import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk


class KnowledgeSourceStatus:
    REGISTERED = "REGISTERED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    STALE = "STALE"


class KnowledgeSource(Base, UUIDPk, TimestampMixin):
    """An approved document. Postgres is authoritative; Qdrant only holds
    the embedded chunks for retrieval."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint("source_uri", "organization_id", "institution_id", name="uq_knowledge_source_uri_tenant", postgresql_nulls_not_distinct=True),
    )

    title: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)  # INLINE_TEXT | LOCAL_FILE | APPROVED_URL | DOCUMENT
    source_uri: Mapped[str] = mapped_column(String)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True
    )
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), nullable=True, index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    visibility: Mapped[str] = mapped_column(String)
    skill_ids: Mapped[list[str]] = mapped_column(ARRAY(String))
    status: Mapped[str] = mapped_column(String, default=KnowledgeSourceStatus.REGISTERED)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    document_version: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    last_ingested_at: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeChunk(Base, UUIDPk, TimestampMixin):
    """Postgres copy of every chunk. The chunk id doubles as the Qdrant point
    id, so re-ingesting the same content upserts instead of duplicating."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String)
    embedding_model: Mapped[str] = mapped_column(String)
