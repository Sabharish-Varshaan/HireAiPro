import uuid

from sqlalchemy import Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk
from app.models.enums import SkillRelationType


class Skill(Base, UUIDPk, TimestampMixin):
    __tablename__ = "skills"

    canonical_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class SkillAlias(Base, UUIDPk, TimestampMixin):
    __tablename__ = "skill_aliases"
    __table_args__ = (UniqueConstraint("alias_normalized", name="uq_skill_alias_norm"),)

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), index=True
    )
    alias: Mapped[str] = mapped_column(String)
    alias_normalized: Mapped[str] = mapped_column(String, index=True)


class SkillRelationship(Base, UUIDPk, TimestampMixin):
    __tablename__ = "skill_relationships"

    from_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), index=True
    )
    to_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id"), index=True
    )
    relation_type: Mapped[SkillRelationType] = mapped_column(String)
