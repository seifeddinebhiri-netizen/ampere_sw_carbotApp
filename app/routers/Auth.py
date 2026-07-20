"""/auth endpoints.

This layer does exactly three things: take HTTP in, call a service, turn domain
errors into status codes. No business logic lives here -- if you find yourself
writing an `if` about users or tokens, it belongs in the service.
"""

from logging import exception

from sys import exception

from fastapi import APIRouter, HTTPException, status

from app.Dependecies import CurrentUser, SessionDep
from app.Exeptions import EmailAlreadyRegistered, InvalidCredentials, InvalidToken
from app.schemas.Auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut,
             status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: SessionDep):
    try:
        user = await AuthService.register(session, body.email, body.password)
    except EmailAlreadyRegistered:
        # 409 Conflict: the request is well-formed, it just clashes with state.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="email already registered")
    return user


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, session: SessionDep):
    try:
        access, refresh = await AuthService.login(session, body.email, body.password)
    except InvalidCredentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid email or password")
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: SessionDep):
    """Trade a refresh token for a new pair. No password needed.

    This is what lets access tokens expire in 15 minutes without the user ever
    noticing.
    """
    try:
        access, new_refresh = await AuthService.refresh_tokens(
            session, body.refresh_token
        )
    except InvalidToken:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid or revoked refresh token")
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, session: SessionDep):
    # Idempotent on purpose: logging out twice isn't an error.
    await AuthService.logout(session, body.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    """Smallest possible protected endpoint -- handy for testing that a token
    works before you go near the car."""
    return user