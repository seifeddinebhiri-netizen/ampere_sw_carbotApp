"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.DataBase.DB import get_session
from app.Exeptions import InvalidToken
from app.DataBase.Models import User
from app.DataBase.Security import decode_access_token
from app.services import AuthService as auth_service

# Reads the "Authorization: Bearer <token>" header, and gives /docs an
# "Authorize" button so you can test protected endpoints in the browser.
bearer_scheme = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    """Turn a bearer token into a User, or 401.

    Put this on an endpoint and it cannot be reached without a valid token.
    That's the whole authentication layer, in one dependency.

    Note the two DB hits vs zero: decode_access_token is pure math (no DB), but
    we then load the user so we can check is_active and give services a real
    object. If you ever need maximum throughput, that lookup is what you'd cache.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        # Bad signature, expired, or malformed -- we don't say which. Telling an
        # attacker "expired" vs "forged" is free information.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return await auth_service.get_user(session, user_id)
    except InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


CurrentUser = Annotated[User, Depends(get_current_user)]