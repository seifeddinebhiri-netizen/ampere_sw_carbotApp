"""Database models.

  users ──1:N──► vehicles        (owner_id)   <- the authorization boundary
  users ──1:N──► refresh_tokens  (user_id)    <- revocation
  command_log ──► users, vehicles (nullable)  <- audit, survives deletion

Passwords and refresh tokens are HASHED, never encrypted, never plaintext.
Email and VIN are plaintext: we query by them, and encrypted columns can't be
indexed usefully.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    # Always store UTC. Timezone bugs are miserable and entirely avoidable.
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # unique=True creates a UNIQUE INDEX -- two jobs at once:
    #   1. correctness: two accounts can't share an email
    #   2. speed: login runs "WHERE email = ?" on every request
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # bcrypt output (~60 chars). Never the password itself.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    vehicles: Mapped[list["Vehicle"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Real VINs are exactly 17 chars. Unique: one physical car, one row.
    vin: Mapped[str] = mapped_column(String(17), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # THE security boundary. Every car endpoint resolves the VIN through this
    # column. The client never sends a VIN -- it sends a token, we find the user,
    # we find THEIR vehicle. That's what stops you opening my AC.
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner: Mapped["User"] = relationship(back_populates="vehicles")

    __table_args__ = (
        # "which cars does this user own?" runs on every car request. Without
        # this index SQLite scans the whole table each time.
        Index("ix_vehicles_owner_id", "owner_id"),
    )

    def __repr__(self) -> str:
        return f"<Vehicle {self.vin}>"


class RefreshToken(Base):
    """Long-lived, revocable token used to mint new short-lived access tokens.

    Why it exists: a JWT is stateless and therefore CANNOT be revoked -- a stolen
    phone keeps working until expiry. Fix: short-lived access token (15 min)
    backed by a refresh token that DOES live in the DB. This row is the
    revocation switch.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # HASHED. This row is a password-equivalent: if the DB leaks and these were
    # plaintext, every session is hijackable.
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # NULL = still valid. Set a timestamp to kill it (logout, stolen phone).
    # We revoke by setting a column rather than DELETE, to keep the trail.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (Index("ix_refresh_tokens_user_id", "user_id"),)

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and self.expires_at > _now()


class CommandLog(Base):
    """Audit trail: who did what to which car, and did it work.

    Not optional for a car. When someone asks "why did my AC run all night",
    this is the only thing that can answer. Write a row for EVERY car-touching
    request.
    """

    __tablename__ = "command_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Nullable + SET NULL: deleting a user must not erase the history.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )

    # Denormalised on purpose: the VIN AS IT WAS at the time. If the vehicle row
    # is later deleted or reassigned, the log still says which car it was.
    vin: Mapped[str] = mapped_column(String(17), nullable=False)

    action: Mapped[str] = mapped_column(String(50), nullable=False)  # "ac.on"

    # The MQTT correlation id -- the thread tying an HTTP request to a broker
    # message to a car response, across three systems' logs.
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # "ok" | "timeout" | "rejected". "timeout" is NOT failure: it means we don't
    # know whether the car acted. The log must preserve that distinction.
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        # Composite index for the query you'll actually run: "history for THIS
        # car, newest first". Filter column first, sort column second.
        Index("ix_command_log_vehicle_created", "vehicle_id", "created_at"),
        Index("ix_command_log_request_id", "request_id"),
    )