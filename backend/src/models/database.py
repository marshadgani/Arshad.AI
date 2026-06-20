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

# Supabase pooler URLs contain 'pooler.supabase.com' as the host, or use
# the username format 'postgres.PROJECT_REF' (Supavisor session/transaction
# mode). asyncpg is incompatible with Supavisor: the pooler rejects the
# prepared-statement protocol and may return ENOTFOUND on tenant lookup.
# Fail fast at startup with an actionable message rather than a cryptic
# asyncpg InternalServerError at first request.
_is_pooler = "pooler.supabase.com" in _db_url or (
    "@" in _db_url
    and _db_url.split("@")[0].rsplit(":", 1)[0].split("/")[-1].startswith("postgres.")
)
if _is_pooler:
    raise RuntimeError(
        "DATABASE_URL points at Supabase's connection pooler "
        f"({_db_url.split('@')[-1].split('/')[0]}), which is incompatible "
        "with asyncpg.\n\n"
        "Fix on Render:\n"
        "  1. Go to Supabase dashboard → Project Settings → Database → Connection string\n"
        "  2. Select 'Direct connection' (NOT 'Connection pooler')\n"
        "  3. Copy the URI (format: postgresql://postgres:PASSWORD@db.PROJECT.supabase.co:5432/postgres)\n"
        "  4. Add +asyncpg after postgresql: → postgresql+asyncpg://...\n"
        "  5. Set DATABASE_URL_DIRECT to that value in Render → Environment\n"
        "  6. Leave DATABASE_URL as-is for local Docker (it uses a local postgres container)\n"
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
