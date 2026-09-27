from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.users import User
from app.schemas.auth import CurrentUser, LoginRequest, SignupRequest, TokenResponse
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
