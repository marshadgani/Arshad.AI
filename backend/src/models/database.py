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

# Supabase / pgbouncer compatibility: when DATABASE_URL points at a pooler
# (any pgbouncer in transaction or session mode), asyncpg's automatic prepared
# statements break because each query may land on a different upstream
# connection. Disable the statement cache when we detect a pooler host.
_engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
if "pooler.supabase.com" in DATABASE_URL or "pgbouncer" in DATABASE_URL:
    _engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
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
