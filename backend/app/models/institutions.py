import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPk
from app.models.enums import UserRole


class Institution(Base, UUIDPk, TimestampMixin):
    __tablename__ = "institutions"

    name: Mapped[str] = mapped_column(String)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class InstitutionMember(Base, UUIDPk, TimestampMixin):
    __tablename__ = "institution_members"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    role: Mapped[UserRole] = mapped_column(String)
    department: Mapped[str | None] = mapped_column(String, nullable=True)


class Department(Base, UUIDPk, TimestampMixin):
    __tablename__ = "departments"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), index=True
    )
    name: Mapped[str] = mapped_column(String)


class Cohort(Base, UUIDPk, TimestampMixin):
    __tablename__ = "cohorts"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id"), index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String)
    graduation_year: Mapped[int | None] = mapped_column(nullable=True)
