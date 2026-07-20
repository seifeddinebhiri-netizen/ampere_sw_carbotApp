"""Request/response shapes for /auth.

Schemas are the CONTRACT with the Android app. They also stop your ORM models
leaking outward: never return a User model directly -- it has password_hash on
it, and one careless response exposes every hash you own.
"""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr                                   # validated, not just a str
    password: str = Field(min_length=8, max_length=72)  # 72 = bcrypt's hard limit


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str      # JWT, 15 min, stateless, sent on every request
    refresh_token: str     # random, 30 days, in the DB, revocable
    token_type: str = "bearer"


class UserOut(BaseModel):
    """Note what's absent: password_hash. Deliberately."""

    id: str
    email: EmailStr

    model_config = {"from_attributes": True}  # allows building this from a User