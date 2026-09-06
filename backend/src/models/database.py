import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .base import Base, TimestampedMixin  # noqa: F401 — re-exported for backward compat
from .db_pooler_guard import reject_transaction_mode_pooler

# Direct connections (db.PROJECT_REF.supabase.co) work too, but new Supabase
# projects resolve that host to an IPv6-only address, which platforms with
# IPv4-only egress (e.g. Render) can't reach — hence the Session mode pooler
# (see db_pooler_guard.py) is the practical default here. statement_cache_size=0
# is a second safeguard so asyncpg never caches/reuses a named prepared
# statement across pooled connections.
_db_url = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
if not _db_url:
    raise RuntimeError(
        "Neither DATABASE_URL_DIRECT nor DATABASE_URL is set. "
        "Copy backend/.env.example to backend/.env and fill in DATABASE_URL."
    )

reject_transaction_mode_pooler(_db_url)

_engine_kwargs: dict = {
    "echo": False,
    "pool_pre_ping": True,
    "connect_args": {"statement_cache_size": 0},
}

engine = create_async_engine(_db_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
