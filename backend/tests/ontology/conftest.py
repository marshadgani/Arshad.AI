"""Shared pytest fixtures for the ontology test suite.

Provides:
- db_engine: async engine pointing at the test Postgres schema
- db_session: per-test transaction-scoped AsyncSession with auto-rollback

Integration tests here require a REAL, reachable Postgres — set
DATABASE_URL_DIRECT (preferred) or DATABASE_URL to a live test database
before running them. The top-level backend/conftest.py sets a fake
DATABASE_URL default for pure-unit-test collection; that fake value is
not connectable, so db_engine below explicitly pings the engine and
skips (rather than erroring the whole run) when nothing real is
reachable.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_DB_URL = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL", "")


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    if not _DB_URL:
        pytest.skip("DATABASE_URL not set — skipping integration tests")
    engine = create_async_engine(
        _DB_URL,
        echo=False,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        async with engine.connect() as conn:
            pass
    except Exception as exc:  # noqa: BLE001 — any connect failure means "no real DB here"
        await engine.dispose()
        pytest.skip(f"Configured DATABASE_URL is not reachable — {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(db_engine):
    """Per-test AsyncSession with auto-rollback via nested transaction.
    Uses SAVEPOINT semantics so each test is fully isolated.
    """
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        nested = await conn.begin_nested()  # SAVEPOINT
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await nested.rollback()  # rollback to SAVEPOINT
            await trans.rollback()
