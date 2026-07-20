"""Hashing and token primitives. Pure functions -- no DB, no HTTP.

Nothing here is hand-rolled crypto. bcrypt and PyJWT do the real work; writing
your own would be writing a vulnerability.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.Config import (
    ACCESS_TOKEN_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET,
    REFRESH_TOKEN_DAYS,
)


# --- Passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with bcrypt.

    bcrypt is deliberately SLOW -- that's the feature. It makes brute-forcing a
    leaked hash expensive. Never MD5/SHA256 for passwords: they're fast, which is
    exactly wrong here.

    bcrypt salts automatically, so the same password hashed twice gives two
    different results. Attackers can't precompute a lookup table.
    """
    pw = password.encode("utf-8")
    if len(pw) > 72:
        # bcrypt silently truncates past 72 BYTES. Reject rather than pretend.
        raise ValueError("password must be 72 bytes or fewer")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Hash the attempt and compare. We never decrypt anything.

    checkpw is constant-time, so it can't be attacked by measuring response time.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# --- Access tokens (JWT) -----------------------------------------------------

def create_access_token(user_id: str) -> str:
    """Mint a short-lived signed token.

    A JWT is SIGNED, not encrypted. Anyone can base64-decode the payload and read
    it. The signature only proves we issued it and nobody edited it.
    So: never put secrets in a JWT.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Verify signature + expiry. Returns user_id, or None if it's no good.

    Pure math -- no database hit. That's what "stateless" buys you.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


# --- Refresh tokens ----------------------------------------------------------

def generate_refresh_token() -> str:
    """secrets, not random. random is predictable and therefore forgeable."""
    return secrets.token_urlsafe(48)


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)


def hash_refresh_token(token: str) -> str:
    """SHA256, not bcrypt -- and that's deliberate.

    bcrypt's slowness protects LOW-ENTROPY human passwords. A 48-byte random
    token can't be brute-forced regardless, so slow hashing buys nothing here and
    would just make every refresh sluggish. Right tool per job.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()