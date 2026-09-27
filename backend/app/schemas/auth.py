import uuid

from pydantic import BaseModel, EmailStr

from app.models.enums import UserRole


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    role: UserRole
    full_name: str


class CurrentUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
