"""Auth business logic.

Notice what this file does NOT import: fastapi. No HTTPException, no status
codes, no Request. It raises domain errors and lets the router decide how to
express them over HTTP. That's what makes it testable and reusable.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.Exeptions import EmailAlreadyRegistered, InvalidCredentials, InvalidToken
from app.DataBase.Models import RefreshToken, User
from app.DataBase.Security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)


async def _issue_refresh_token(session: AsyncSession, user_id: str) -> str:
    """Create a refresh token, store only its HASH, return the plaintext once.

    This is the only moment the plaintext exists. The client keeps it; we keep a
    hash. If our DB leaks, the hashes can't be used to mint tokens.
    """
    token = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(token),
            expires_at=refresh_token_expiry(),
        )
    )
    return token


async def register(session: AsyncSession, email: str, password: str) -> User:
    existing = await session.scalar(select(User).where(User.email == email))
    if existing:
        raise EmailAlreadyRegistered(email)

    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def login(session: AsyncSession, email: str, password: str) -> tuple[str, str]:
    """Verify credentials, return (access_token, refresh_token)."""
    user = await session.scalar(select(User).where(User.email == email))

    # Same error whether the email is unknown or the password is wrong.
    # Distinguishing them tells an attacker which emails are registered --
    # that's account enumeration, and it's free to avoid.
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    if not user.is_active:
        raise InvalidCredentials()

    refresh = await _issue_refresh_token(session, user.id)
    await session.commit()
    return create_access_token(user.id), refresh


async def refresh_tokens(session: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """Trade a valid refresh token for a new pair.

    We look the token up by its HASH -- we can't search for the plaintext,
    because we never stored it. Hash the incoming one and match.
    """
    token_hash = hash_refresh_token(refresh_token)
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if row is None or not row.is_valid:
        raise InvalidToken()

    # ROTATION: burn the old token, issue a new one. If a refresh token is ever
    # stolen and used, the real user's next refresh fails -- which is how you
    # DETECT theft instead of silently sharing the account forever.
    row.revoked_at = datetime.now(timezone.utc)

    new_refresh = await _issue_refresh_token(session, row.user_id)
    await session.commit()
    return create_access_token(row.user_id), new_refresh


async def logout(session: AsyncSession, refresh_token: str) -> None:
    """Revoke one refresh token.

    The user's access token stays valid until it expires (<=15 min) -- that
    window is the price of stateless JWTs, and it's why we keep expiry short.
    """
    token_hash = hash_refresh_token(refresh_token)
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if row and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()


async def get_user(session: AsyncSession, user_id: str) -> User:
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise InvalidToken()
    return user