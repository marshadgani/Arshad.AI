"""Unit tests for make_sync_via_dag() in personal/_shared.py.

All I/O is mocked — no real DB connection required.
Covers idempotency, no-eager-write, and error surfacing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.integrations.base import EnqueuedResult, IntegrationError
from src.integrations.personal._shared import make_sync_via_dag
from src.models.integration import Integration
from src.services.dag_queue import EnqueueConflict, EnqueueOutcome


def _make_integration(user_id: uuid.UUID | None = None) -> Integration:
    row = MagicMock(spec=Integration)
    row.user_id = user_id or uuid.uuid4()
    row.slug = "google_calendar"
    row.last_synced_at = None
    row.last_error = None
    return row


@pytest.fixture()
def db() -> AsyncMock:
    return AsyncMock()


# TC-001 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_make_sync_via_dag_new_row_returns_enqueued_result(db):
    """TC-001: No existing live row → new DagTriggerQueue row created;
    returns EnqueuedResult with a job_id."""
    outcome = EnqueueOutcome(
        job_id=str(uuid.uuid4()), dag_id="calendar_ingestor", deduped=False
    )
    with patch(
        "src.integrations.personal._shared.dag_queue.enqueue_deduped",
        new=AsyncMock(return_value=outcome),
    ):
        sync_fn = make_sync_via_dag("calendar_ingestor")
        integration = _make_integration()
        result = await sync_fn(integration=integration, db=db)

    assert isinstance(result, EnqueuedResult)
    assert result.job_id == outcome.job_id
    assert result.dag_id == "calendar_ingestor"
    assert result.deduped is False
    assert "Queued" in result.summary


# TC-002 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_make_sync_via_dag_existing_pending_deduped(db):
    """TC-002: Existing pending row → returns EnqueuedResult referencing existing job;
    no new row inserted (deduped=True); summary indicates no duplicate."""
    existing_id = str(uuid.uuid4())
    outcome = EnqueueOutcome(
        job_id=existing_id, dag_id="calendar_ingestor", deduped=True
    )
    with patch(
        "src.integrations.personal._shared.dag_queue.enqueue_deduped",
        new=AsyncMock(return_value=outcome),
    ):
        sync_fn = make_sync_via_dag("calendar_ingestor")
        result = await sync_fn(integration=_make_integration(), db=db)

    assert isinstance(result, EnqueuedResult)
    assert result.job_id == existing_id
    assert result.deduped is True
    assert "already queued" in result.summary.lower()


# TC-003 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_make_sync_via_dag_no_eager_last_synced_at_write(db):
    """TC-003: make_sync_via_dag must NOT write integration.last_synced_at
    or last_error — those fields are owned by runner.py after real completion.
    Regression guard for the original eager-write bug."""
    outcome = EnqueueOutcome(
        job_id=str(uuid.uuid4()), dag_id="email_ingestor", deduped=False
    )
    integration = _make_integration()
    with patch(
        "src.integrations.personal._shared.dag_queue.enqueue_deduped",
        new=AsyncMock(return_value=outcome),
    ):
        sync_fn = make_sync_via_dag("email_ingestor")
        await sync_fn(integration=integration, db=db)

    assert integration.last_synced_at is None, (
        "last_synced_at must not be set during enqueue"
    )
    assert integration.last_error is None, "last_error must not be set during enqueue"


# TC-004 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_make_sync_via_dag_enqueue_conflict_raises_integration_error(db):
    """TC-004: EnqueueConflict from dag_queue → raises IntegrationError
    with code 'sync_enqueue_conflict'."""
    with patch(
        "src.integrations.personal._shared.dag_queue.enqueue_deduped",
        new=AsyncMock(side_effect=EnqueueConflict("calendar_ingestor")),
    ):
        sync_fn = make_sync_via_dag("calendar_ingestor")
        with pytest.raises(IntegrationError) as exc_info:
            await sync_fn(integration=_make_integration(), db=db)

    assert exc_info.value.code == "sync_enqueue_conflict"


# TC-005 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_make_sync_via_dag_requires_user_id(db):
    """TC-005: integration.user_id is None → raises IntegrationError
    with code 'no_user' before any enqueue attempt."""
    with patch(
        "src.integrations.personal._shared.dag_queue.enqueue_deduped", new=AsyncMock()
    ) as mock_enqueue:
        sync_fn = make_sync_via_dag("github_ingestor")
        integration = _make_integration(user_id=None)
        integration.user_id = None
        with pytest.raises(IntegrationError) as exc_info:
            await sync_fn(integration=integration, db=db)

    assert exc_info.value.code == "no_user"
    mock_enqueue.assert_not_called()


# TC-006 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_make_sync_via_dag_completed_row_does_not_dedupe(db):
    """TC-006: Only pending/picked rows gate new enqueues. A completed row
    for the same (user, dag_id) should allow a fresh enqueue (deduped=False)."""
    fresh_id = str(uuid.uuid4())
    outcome = EnqueueOutcome(job_id=fresh_id, dag_id="github_ingestor", deduped=False)
    with patch(
        "src.integrations.personal._shared.dag_queue.enqueue_deduped",
        new=AsyncMock(return_value=outcome),
    ):
        sync_fn = make_sync_via_dag("github_ingestor")
        result = await sync_fn(integration=_make_integration(), db=db)

    assert result.job_id == fresh_id
    assert result.deduped is False
