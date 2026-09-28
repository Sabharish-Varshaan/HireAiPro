from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models.users import User
from app.models.enums import UserRole
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse


class AuthError(Exception):
    pass


SELF_SIGNUP_ROLES = {UserRole.STUDENT, UserRole.RECRUITER, UserRole.COMPANY_ADMIN, UserRole.HIRING_MANAGER,
                     UserRole.INSTITUTION_ADMIN}


async def signup(db: AsyncSession, payload: SignupRequest) -> TokenResponse:
    if payload.role not in SELF_SIGNUP_ROLES:
        # Platform admins (and invited institution staff) are never self-registered.
        raise AuthError("This role cannot be self-registered")
    if len(payload.password) < 8:
        raise AuthError("Password must be at least 8 characters")
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise AuthError("Email already registered")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token, user_id=user.id, role=user.role, full_name=user.full_name
    )


async def login(db: AsyncSession, payload: LoginRequest) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise AuthError("Invalid credentials")
    if not user.is_active:
        raise AuthError("Account disabled")
    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token, user_id=user.id, role=user.role, full_name=user.full_name
    )
