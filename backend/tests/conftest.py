"""Nested conftest.py — real-Postgres fixtures for @pytest.mark.pg tests.

This file is intentionally separate from the top-level backend/conftest.py
which already calls os.environ.setdefault('DATABASE_URL', ...) with a fake
localhost DSN and inserts backend/ into sys.path.  We must NOT repeat those
calls here; they are idempotent but confusing, and duplicating them would
mask the entire purpose of _require_test_database_url().

Highlight — HIGH 3 (FEAT-144 retry):
  The pg_session fixture requires TEST_DATABASE_URL explicitly with no
  fallback to DATABASE_URL.  If it fell back, the fake
  'postgresql+asyncpg://user:pass@localhost/testdb' DSN set by the
  top-level conftest would be silently used, and every trigger / CHECK /
  ON CONFLICT assertion would fail or be skipped against a non-existent host.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    create_async_engine,
)

# ── pytest marker registration ────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:  # noqa: D401
    """Register the 'pg' marker so pytest doesn't emit an unknown-marker warning."""
    config.addinivalue_line(
        "markers",
        "pg: mark test as requiring a real Postgres instance (set TEST_DATABASE_URL).",
    )


# ── DSN guard ─────────────────────────────────────────────────────────────────


def _require_test_database_url() -> str:
    """Return TEST_DATABASE_URL or raise a clear RuntimeError.

    No fallback to DATABASE_URL is intentional: the top-level backend/conftest.py
    sets DATABASE_URL to a fake 'postgresql+asyncpg://user:pass@localhost/testdb'
    DSN.  Falling back there would silently run trigger/CHECK/ON CONFLICT tests
    against a non-existent host, producing connection errors rather than the
    expected SQL assertion failures.

    Set TEST_DATABASE_URL to a real Postgres DSN before running @pytest.mark.pg
    tests, e.g.:
        TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/arshad_ai
    """
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "TEST_DATABASE_URL env var is required for @pytest.mark.pg tests; "
            "set it to a real Postgres DSN"
        )
    return dsn


# ── pg_session fixture ────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def pg_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Yield a real Postgres connection that wraps every test in a SAVEPOINT."""
    dsn = _require_test_database_url()
    engine = create_async_engine(
        dsn, echo=False, connect_args={"statement_cache_size": 0}
    )
    async with engine.connect() as conn:
        await conn.begin()
        try:
            yield conn
        finally:
            await conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT set_config('app.allow_visibility_promotion', 'false', false)"
                )
            )
            await conn.rollback()
    await engine.dispose()


@pytest_asyncio.fixture()
async def pg_session(
    pg_connection: AsyncConnection,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession joined to the test-scoped outer transaction."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(
        bind=pg_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with factory() as session:
        yield session


# ── committed_user fixture ────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def committed_user(pg_session: AsyncSession):
    """Insert and flush a User row.  Used as the tenant anchor in all pg tests."""
    import uuid

    from src.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        name="Test User",
    )
    pg_session.add(user)
    await pg_session.flush()
    return user
