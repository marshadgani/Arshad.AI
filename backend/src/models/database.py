import os
import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Copy backend/.env.example to backend/.env and fill it in."
    )

# Supabase's transaction pooler (Supavisor, port 6543) keeps stale named
# prepared statements on backend connections between logical sessions.
# asyncpg's default counter-based names (__asyncpg_stmt_N__) start at 0 on
# every new connection object, so a new connection hitting the same backend
# tries to PREPARE __asyncpg_stmt_5__ that already exists
# → DuplicatePreparedStatementError.
#
# Fix: generate UUID-based names so no two prepared statements across any
# number of connections can ever share a name.  statement_cache_size=0 still
# disables caching (each statement is deallocated after use); the UUID prefix
# makes the one-per-query names globally unique so stale leftovers on the
# backend never collide with fresh ones.
_engine_kwargs: dict = {
    "echo": False,
    "pool_pre_ping": True,
    "connect_args": {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda _: f"__asyncpg_{uuid.uuid4().hex}__",
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
