"""TC-041 through TC-048 — sync_completion.finalize_sync unit tests.

REQUIREMENTS COVERED:
  REQ-T41  success=True → Integration.last_synced_at set to now
  REQ-T42  success=True → Integration.last_error cleared to None
  REQ-T43  success=False → Integration.last_error set to error_text
  REQ-T44  success=False → Integration.last_synced_at NOT written
  REQ-T45  Integration row not found → warning logged, no exception raised
  REQ-T46  Unrelated dag_id (no slug mapping) → returns immediately, no DB query
  REQ-T47  DB write failure → caught and swallowed (never masks ingestion result)
  REQ-T48  slug_for_dag_id covers all three DAG-backed providers
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSlugForDagId:
    """TC-048 — slug_for_dag_id must return the correct slug for each DAG."""

    def test_calendar_ingestor_maps_to_google_calendar(self):
        from src.integrations.registry import slug_for_dag_id

        assert slug_for_dag_id("calendar_ingestor") == "google_calendar"

    def test_email_ingestor_maps_to_gmail(self):
        from src.integrations.registry import slug_for_dag_id

        assert slug_for_dag_id("email_ingestor") == "gmail"

    def test_github_ingestor_maps_to_github(self):
        from src.integrations.registry import slug_for_dag_id

        assert slug_for_dag_id("github_ingestor") == "github"

    def test_unknown_dag_id_returns_none(self):
        from src.integrations.registry import slug_for_dag_id

        assert slug_for_dag_id("analytics_processor") is None


def _mock_session(scalar_return, begin_enter_side_effect=None):
    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    begin_ctx = AsyncMock()
    if begin_enter_side_effect is not None:
        begin_ctx.__aenter__ = AsyncMock(side_effect=begin_enter_side_effect)
    else:
        begin_ctx.__aenter__ = AsyncMock(return_value=begin_ctx)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_db.begin = MagicMock(return_value=begin_ctx)
    mock_db.scalar = AsyncMock(return_value=scalar_return)

    return MagicMock(return_value=mock_db)


@pytest.mark.asyncio
async def test_finalize_sync_success_writes_last_synced_at_and_clears_error():
    """TC-041+TC-042 — success=True writes last_synced_at and sets last_error=None."""
    user_id = uuid.uuid4()

    fake_integration = MagicMock()
    fake_integration.last_synced_at = None
    fake_integration.last_error = "previous error"

    mock_session_local = _mock_session(fake_integration)

    with patch(
        "src.services.ingestion.sync_completion.AsyncSessionLocal", mock_session_local
    ):
        with patch(
            "src.services.ingestion.sync_completion.slug_for_dag_id",
            return_value="google_calendar",
        ):
            from src.services.ingestion.sync_completion import finalize_sync

            await finalize_sync(
                dag_id="calendar_ingestor",
                user_id=user_id,
                success=True,
                error_text=None,
            )

    assert fake_integration.last_synced_at is not None
    assert isinstance(fake_integration.last_synced_at, datetime)
    assert fake_integration.last_synced_at.tzinfo is not None
    assert fake_integration.last_error is None


@pytest.mark.asyncio
async def test_finalize_sync_failure_writes_last_error_not_last_synced_at():
    """TC-043+TC-044 — success=False: last_error=error_text, last_synced_at untouched."""
    user_id = uuid.uuid4()

    fake_integration = MagicMock()
    fake_integration.last_synced_at = None
    fake_integration.last_error = None

    mock_session_local = _mock_session(fake_integration)

    with patch(
        "src.services.ingestion.sync_completion.AsyncSessionLocal", mock_session_local
    ):
        with patch(
            "src.services.ingestion.sync_completion.slug_for_dag_id",
            return_value="google_calendar",
        ):
            from src.services.ingestion.sync_completion import finalize_sync

            await finalize_sync(
                dag_id="calendar_ingestor",
                user_id=user_id,
                success=False,
                error_text="CalendarAPIError: quota exceeded",
            )

    assert fake_integration.last_error == "CalendarAPIError: quota exceeded"
    assert fake_integration.last_synced_at is None


@pytest.mark.asyncio
async def test_finalize_sync_missing_integration_row_logs_warning_no_raise():
    """TC-045 — No Integration row for user_id+slug: logs warning and returns normally."""
    user_id = uuid.uuid4()

    mock_session_local = _mock_session(None)  # no row found

    with patch(
        "src.services.ingestion.sync_completion.AsyncSessionLocal", mock_session_local
    ):
        with patch(
            "src.services.ingestion.sync_completion.slug_for_dag_id",
            return_value="google_calendar",
        ):
            from src.services.ingestion.sync_completion import finalize_sync

            await finalize_sync(
                dag_id="calendar_ingestor",
                user_id=user_id,
                success=True,
                error_text=None,
            )  # must not raise


@pytest.mark.asyncio
async def test_finalize_sync_unknown_dag_id_returns_without_db_access():
    """TC-046 — dag_id with no slug mapping (e.g. analytics_processor) returns immediately."""
    user_id = uuid.uuid4()
    mock_session_local = MagicMock()

    with patch(
        "src.services.ingestion.sync_completion.AsyncSessionLocal", mock_session_local
    ):
        with patch(
            "src.services.ingestion.sync_completion.slug_for_dag_id",
            return_value=None,
        ):
            from src.services.ingestion.sync_completion import finalize_sync

            await finalize_sync(
                dag_id="analytics_processor",
                user_id=user_id,
                success=True,
                error_text=None,
            )

    mock_session_local.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_sync_db_write_failure_is_swallowed():
    """TC-047 — If the DB write raises, finalize_sync swallows it and returns normally."""
    user_id = uuid.uuid4()

    mock_session_local = _mock_session(
        None, begin_enter_side_effect=Exception("DB connection lost")
    )

    with patch(
        "src.services.ingestion.sync_completion.AsyncSessionLocal", mock_session_local
    ):
        with patch(
            "src.services.ingestion.sync_completion.slug_for_dag_id",
            return_value="google_calendar",
        ):
            from src.services.ingestion.sync_completion import finalize_sync

            await finalize_sync(
                dag_id="calendar_ingestor",
                user_id=user_id,
                success=True,
                error_text=None,
            )  # must not propagate the DB exception
