"""Invitations, activation and password reset.

Tokens are 256-bit random values. Only sha256(token) is stored, so a database read cannot
be turned into a working link; each token is single-use and expires. Nobody but the account
owner ever sets or sees a password.
"""

import datetime as dt
import hashlib
import secrets
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.models.accounts import EmailOutbox, Invitation, InstitutionStudent, PasswordReset
from app.models.enums import UserRole
from app.models.institutions import Institution, InstitutionMember
from app.models.students import StudentProfile
from app.models.users import User
from app.schemas.auth import TokenResponse

MIN_PASSWORD = 8


class AccountError(Exception):
    """Message is safe to show to the caller."""


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def outbox_enabled() -> bool:
    s = get_settings()
    return s.APP_ENV in {e.strip() for e in s.EMAIL_OUTBOX_ENVS.split(",")}


async def send_email(db: AsyncSession, to: str, subject: str, body: str, link: str | None = None) -> None:
    """No real provider is wired. In development/demo the message goes to email_outbox."""
    if outbox_enabled():
        db.add(EmailOutbox(to_email=to, subject=subject, body=body, link=link))


def check_password(pw: str) -> None:
    if len(pw) < MIN_PASSWORD:
        raise AccountError(f"Password must be at least {MIN_PASSWORD} characters")


async def create_invitation(db: AsyncSession, *, email: str, role: UserRole, created_by: uuid.UUID | None,
                            institution_id=None, organization_id=None, institution_student_id=None,
                            subject: str, intro: str) -> Invitation:
    """Revokes earlier open invitations for the same email/role/scope, so a resend invalidates the old link."""
    s = get_settings()
    q = update(Invitation).where(Invitation.email == email, Invitation.role == role.value,
                                 Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))
    if institution_student_id:
        q = q.where(Invitation.institution_student_id == institution_student_id)
    await db.execute(q.values(revoked_at=_now()))
    raw = new_token()
    inv = Invitation(email=email, role=role.value, institution_id=institution_id, organization_id=organization_id,
                     institution_student_id=institution_student_id, token_hash=hash_token(raw), created_by=created_by,
                     expires_at=_now() + dt.timedelta(hours=s.INVITE_TTL_HOURS))
    db.add(inv)
    link = f"{s.FRONTEND_BASE_URL}/claim?token={raw}"
    await send_email(db, email, subject, f"{intro}\n\nActivate your account: {link}\nThis link works once and expires in "
                                          f"{s.INVITE_TTL_HOURS} hours.", link)
    await db.flush()
    return inv


async def _open_invitation(db: AsyncSession, raw: str) -> Invitation:
    inv = await db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(raw)))
    # one generic message for unknown / used / revoked / expired: no oracle for token state
    if inv is None or inv.accepted_at or inv.revoked_at or inv.expires_at <= _now():
        raise AccountError("This invitation link is invalid or has expired")
    return inv


async def describe_invitation(db: AsyncSession, raw: str) -> dict:
    inv = await _open_invitation(db, raw)
    inst = await db.get(Institution, inv.institution_id) if inv.institution_id else None
    student = await db.get(InstitutionStudent, inv.institution_student_id) if inv.institution_student_id else None
    name = " ".join(x for x in [getattr(student, "first_name", None), getattr(student, "last_name", None)] if x)
    return {"email": inv.email, "role": inv.role, "institution_name": inst.name if inst else None, "full_name": name or None}


async def accept_invitation(db: AsyncSession, raw: str, password: str, full_name: str | None) -> TokenResponse:
    check_password(password)
    inv = await _open_invitation(db, raw)
    # Atomic claim: two concurrent accepts cannot both succeed.
    claimed = await db.execute(update(Invitation).where(Invitation.id == inv.id, Invitation.accepted_at.is_(None))
                               .values(accepted_at=_now()))
    if claimed.rowcount != 1:
        raise AccountError("This invitation link is invalid or has expired")
    if await db.scalar(select(User.id).where(User.email == inv.email)):
        await db.rollback()
        raise AccountError("An account already exists for this email. Sign in instead.")
    student = await db.get(InstitutionStudent, inv.institution_student_id) if inv.institution_student_id else None
    name = full_name or " ".join(x for x in [getattr(student, "first_name", None), getattr(student, "last_name", None)] if x) or inv.email
    user = User(email=inv.email, password_hash=hash_password(password), full_name=name, role=inv.role)
    db.add(user)
    await db.flush()
    if inv.role == UserRole.STUDENT.value and student is not None:
        db.add(StudentProfile(user_id=user.id, institution_id=student.institution_id, cohort_id=student.cohort_id))
        student.user_id, student.status = user.id, "ACTIVE"
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id, user.role), user_id=user.id, role=user.role,
                         full_name=user.full_name)


async def request_password_reset(db: AsyncSession, email: str) -> None:
    """Always succeeds from the caller's point of view (no account enumeration)."""
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        return
    s = get_settings()
    await db.execute(update(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
                     .values(used_at=_now()))
    raw = new_token()
    db.add(PasswordReset(user_id=user.id, token_hash=hash_token(raw),
                         expires_at=_now() + dt.timedelta(minutes=s.RESET_TTL_MINUTES)))
    link = f"{s.FRONTEND_BASE_URL}/reset-password?token={raw}"
    await send_email(db, email, "Reset your HireAiPro password",
                     f"Reset your password: {link}\nThis link works once and expires in {s.RESET_TTL_MINUTES} minutes.", link)
    await db.commit()


async def reset_password(db: AsyncSession, raw: str, password: str) -> None:
    check_password(password)
    pr = await db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(raw)))
    if pr is None or pr.used_at or pr.expires_at <= _now():
        raise AccountError("This reset link is invalid or has expired")
    claimed = await db.execute(update(PasswordReset).where(PasswordReset.id == pr.id, PasswordReset.used_at.is_(None))
                               .values(used_at=_now()))
    if claimed.rowcount != 1:
        raise AccountError("This reset link is invalid or has expired")
    user = await db.get(User, pr.user_id)
    user.password_hash = hash_password(password)
    await db.commit()


async def provision_placement_officer(db: AsyncSession, user: User, institution_name: str) -> Institution:
    inst = Institution(name=institution_name.strip(), created_by_user_id=user.id)
    db.add(inst)
    await db.flush()
    db.add(InstitutionMember(institution_id=inst.id, user_id=user.id, role=UserRole.PLACEMENT_OFFICER))
    return inst
