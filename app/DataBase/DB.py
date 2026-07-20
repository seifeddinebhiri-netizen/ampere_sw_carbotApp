"""Database engine and sessions."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import sys
from pathlib import Path

# Step up twice: from 'dir' to 'app', then to the folder containing 'app'
root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(root_dir))
from app.Config import DATABASE_URL
from app.DataBase.Models import Base

# SQLite is a single FILE -- no server, no port, no credentials. Moving to
# Postgres later changes this URL and nothing else, because SQLAlchemy renders
# the right dialect from the same query objects.
engine = create_async_engine(DATABASE_URL, echo=False)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create missing tables.

    NOT a migration tool: it won't ALTER existing tables when you change a model.
    The first time you add a column and nothing happens, this is why. Switch to
    Alembic once the schema starts moving.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, always closed."""
    async with SessionLocal() as session:
        yield session