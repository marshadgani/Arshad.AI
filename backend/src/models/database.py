import os
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Prefer DATABASE_URL_DIRECT (bypasses Supabase/PgBouncer transaction pooler).
# asyncpg's prepared-statement LRU cache collides across pooler connections —
# the pooler routes PREPARE and EXECUTE to different Postgres backends, so the
# named statement is unknown on the backend that receives EXECUTE.
# Disabling statement_cache_size eliminates those DuplicatePreparedStatementError
# crashes. Falls back to DATABASE_URL for local dev and non-pooled environments.
DATABASE_URL = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "Neither DATABASE_URL_DIRECT nor DATABASE_URL is set. "
        "Copy backend/.env.example to backend/.env and fill in DATABASE_URL."
    )

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={
        "statement_cache_size": 0
    },  # required when routed through Supabase/PgBouncer
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class TimestampedMixin:
    """created_at / updated_at columns with PG-side defaults.

    Lifted out of dashboard.py and domain.py — both had identical copies
    that drifted whenever audit fields were added.
    """

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
