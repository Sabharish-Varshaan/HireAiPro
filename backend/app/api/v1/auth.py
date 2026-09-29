from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.users import User
from app.schemas.auth import (AcceptInvitation, CurrentUser, ForgotPassword, LoginRequest, ResetPassword,
                              SignupRequest, TokenResponse)
from app.services.accounts import service as accounts
from app.services.auth.service import AuthError, login, signup

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
async def signup_route(payload: SignupRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await signup(db, payload)
    except AuthError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/login", response_model=TokenResponse)
async def login_route(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await login(db, payload)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


@router.get("/me", response_model=CurrentUser)
async def me_route(user: User = Depends(get_current_user)):
    return CurrentUser(id=user.id, email=user.email, full_name=user.full_name, role=user.role)


@router.get("/invitations/{token}")
async def invitation_info(token: str, db: AsyncSession = Depends(get_db)):
    try:
        return await accounts.describe_invitation(db, token)
    except accounts.AccountError as exc:
        raise HTTPException(410, str(exc)) from exc


@router.post("/invitations/accept", response_model=TokenResponse)
async def accept_invitation(payload: AcceptInvitation, db: AsyncSession = Depends(get_db)):
    try:
        return await accounts.accept_invitation(db, payload.token, payload.password, payload.full_name)
    except accounts.AccountError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/password/forgot", status_code=202)
async def forgot_password(payload: ForgotPassword, db: AsyncSession = Depends(get_db)):
    await accounts.request_password_reset(db, payload.email)
    return {"detail": "If an account exists for that email, a reset link has been sent."}


@router.post("/password/reset")
async def reset_password(payload: ResetPassword, db: AsyncSession = Depends(get_db)):
    try:
        await accounts.reset_password(db, payload.token, payload.password)
    except accounts.AccountError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"detail": "Password updated. You can sign in now."}
