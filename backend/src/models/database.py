import os
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy backend/.env.example to backend/.env and fill it in."
    )

# Always disable asyncpg's server-side prepared-statement cache.
#
# When DATABASE_URL points at any pgbouncer-style pooler in transaction or
# statement mode (Supabase pooler, RDS Proxy, custom pgbouncer, Neon's pooler
# endpoint), asyncpg's auto-prepared statements collide: the named statement
# `__asyncpg_stmt_N__` is registered on one upstream connection but a
# subsequent query in the same logical session lands on a different upstream
# connection that already has its own statement N — DuplicatePreparedStatement,
# 5xx, app down. The earlier substring check (pooler.supabase.com|pgbouncer)
# missed prod URLs that pool without those tokens (e.g. RDS Proxy hosts).
#
# Disabling the cache costs one parse per query (dominated by network RTT) and
# eliminates the failure mode regardless of how the URL is shaped. Direct
# (non-pooled) connections work fine without prepared-statement caching.
_engine_kwargs: dict = {
    "echo": False,
    "pool_pre_ping": True,
    "connect_args": {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
}

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
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


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
