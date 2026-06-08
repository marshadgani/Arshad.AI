import os
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Supabase's transaction pooler (Supavisor, port 6543) is incompatible with
# asyncpg's prepared statement protocol: the pooler routes each statement to an
# arbitrary backend, so PREPARE and DEALLOCATE can land on different backends,
# leaving stale named statements (e.g. __asyncpg_stmt_5__) that collide with
# counter-based names from the next asyncpg connection object.
#
# The only reliable fix is to bypass the pooler and connect directly to Postgres
# (db.PROJECT_REF.supabase.co:5432).  Set DATABASE_URL_DIRECT to that URL on
# Render; falls back to DATABASE_URL so local docker-compose needs no change.
# statement_cache_size=0 is kept as a secondary safeguard.
_db_url = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
if not _db_url:
    raise RuntimeError(
        "Neither DATABASE_URL_DIRECT nor DATABASE_URL is set. "
        "Copy backend/.env.example to backend/.env and fill in DATABASE_URL."
    )

_engine_kwargs: dict = {
    "echo": False,
    "pool_pre_ping": True,
    "connect_args": {"statement_cache_size": 0},
}

engine = create_async_engine(_db_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class TimestampedMixin:
    """created_at / updated_at columns with PG-side defaults."""

    created_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
