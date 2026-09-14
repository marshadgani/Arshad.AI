"""Unit tests for ingestion runner's single write-site for
Integration.last_synced_at / last_error (FEAT-144).

All DB writes are isolated via a mocked AsyncSessionLocal.

Patch target note: these tests patch ``src.models.database.AsyncSessionLocal``,
NOT ``src.services.ingestion.runner.AsyncSessionLocal``. The latter does not
exist — runner.py imports the sessionmaker *inside* ``_mark_integration_synced``
on purpose, because ``src.models.database`` raises at import time when
DATABASE_URL is unset, and the Airflow scheduler must be able to import the
runner while parsing DAG files without database credentials. Patching the
source module works precisely because the function-local import re-reads the
attribute on every call. Do not "fix" this by hoisting the import in runner.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.services.ingestion.runner import _mark_integration_synced


def _mock_session(integration: MagicMock | None) -> AsyncMock:
    """Build an AsyncSession mock that returns `integration` on scalar()."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.scalar = AsyncMock(return_value=integration)
    session.commit = AsyncMock()
    return session


def _mock_integration() -> MagicMock:
    row = MagicMock()
    row.last_synced_at = None
    row.last_error = None
    return row


# TC-040 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mark_integration_synced_success_sets_last_synced_at():
    """TC-040: Successful dispatch for calendar_ingestor → last_synced_at
    updated to now, last_error cleared."""
    integration = _mock_integration()
    session = _mock_session(integration)

    with (
        patch("src.models.database.AsyncSessionLocal", return_value=session),
        patch(
            "src.services.ingestion.runner.dag_to_slug", return_value="google_calendar"
        ),
    ):
        await _mark_integration_synced(
            user_id=uuid.uuid4(), dag_id="calendar_ingestor", error=None
        )

    assert integration.last_error is None
    assert integration.last_synced_at is not None
    session.commit.assert_awaited_once()


# TC-041 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mark_integration_synced_failure_sets_last_error_not_synced_at():
    """TC-041: Exception path → last_error set to '{type}: {msg}';
    last_synced_at NOT updated."""
    integration = _mock_integration()
    original_synced_at = integration.last_synced_at
    session = _mock_session(integration)

    with (
        patch("src.models.database.AsyncSessionLocal", return_value=session),
        patch("src.services.ingestion.runner.dag_to_slug", return_value="gmail"),
    ):
        await _mark_integration_synced(
            user_id=uuid.uuid4(),
            dag_id="email_ingestor",
            error="TokenExpiredError: access token expired",
        )

    assert "TokenExpiredError" in integration.last_error
    assert integration.last_synced_at == original_synced_at
    session.commit.assert_awaited_once()


# TC-042 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mark_integration_synced_unknown_dag_id_no_op():
    """TC-042: dag_to_slug returns None (e.g. analytics_processor) → silent
    no-op, no session open, no commit."""
    session = _mock_session(None)

    with (
        patch("src.services.ingestion.runner.dag_to_slug", return_value=None),
        patch("src.models.database.AsyncSessionLocal", return_value=session),
    ):
        await _mark_integration_synced(
            user_id=uuid.uuid4(), dag_id="analytics_processor", error=None
        )

    session.commit.assert_not_awaited()


# TC-043 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mark_integration_synced_missing_integration_row_no_op():
    """TC-043: No Integration row found for (user, slug) → silent no-op,
    no commit."""
    session = _mock_session(None)

    with (
        patch("src.models.database.AsyncSessionLocal", return_value=session),
        patch(
            "src.services.ingestion.runner.dag_to_slug", return_value="google_calendar"
        ),
    ):
        await _mark_integration_synced(
            user_id=uuid.uuid4(), dag_id="calendar_ingestor", error=None
        )

    session.commit.assert_not_awaited()
