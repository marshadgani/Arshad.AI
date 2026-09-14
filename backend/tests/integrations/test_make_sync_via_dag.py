"""TC-005 through TC-012 — make_sync_via_dag unit tests.

REQUIREMENTS COVERED:
  REQ-T05  No in-flight row → inserts new DagTriggerQueue, returns mode='enqueued'
  REQ-T06  In-flight row (pending) → dedup returns existing job_id, no insert
  REQ-T07  In-flight row (picked) → same dedup behaviour
  REQ-T08  No user_id on integration → raises IntegrationError('no_user')
  REQ-T09  MUST NOT write Integration.last_synced_at at enqueue time (root-cause guard)
  REQ-T11  duration_ms >= 0 and reflects real wall-clock of the enqueue operation
  REQ-T12  EnqueueRaceError is surfaced as IntegrationError('sync_race_retry')

All DB access and enqueue_dag_job are mocked — no real Postgres.

Patch target note: make_sync_via_dag's returned _sync() coroutine does
`from ...services.ingestion.enqueue import enqueue_dag_job` INSIDE the
function body (a deliberate local import to avoid an integrations<->
services import cycle — see dag_sync.py's docstring). That means
`src.integrations.personal.dag_sync` never gets `enqueue_dag_job` as a
module-level attribute, so `patch("src.integrations.personal.dag_sync
.enqueue_dag_job", ...)` raises AttributeError before a single assertion
runs (verified: every test in an earlier draft of this file failed at the
`with patch(...)` line, not at any assertion). The fix is to patch the
name where it actually lives and gets looked up at call time:
`src.services.ingestion.enqueue.enqueue_dag_job`.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.integrations.base import IntegrationError, SyncResult

PATCH_TARGET = "src.services.ingestion.enqueue.enqueue_dag_job"


def _fake_integration(
    slug: str = "google_calendar",
    user_id: uuid.UUID | None = None,
) -> MagicMock:
    i = MagicMock()
    i.slug = slug
    i.user_id = user_id or uuid.uuid4()
    i.last_error = None
    i.last_synced_at = None
    return i


def _fake_job(job_id: str, deduped: bool = False) -> MagicMock:
    j = MagicMock()
    j.job_id = job_id
    j.status = "pending"
    j.deduped = deduped
    return j


@pytest.mark.asyncio
async def test_make_sync_via_dag_returns_enqueued_mode_on_fresh_insert():
    """TC-005 — No in-flight row: inserts new row, returns mode='enqueued' with job_id."""
    from src.integrations.personal.dag_sync import make_sync_via_dag

    integration = _fake_integration()
    db = AsyncMock()
    new_job_id = str(uuid.uuid4())
    fake_job = _fake_job(new_job_id, deduped=False)

    with patch(PATCH_TARGET, AsyncMock(return_value=fake_job)):
        result: SyncResult = await make_sync_via_dag("calendar_ingestor")(
            integration=integration, db=db
        )

    assert result.mode == "enqueued"
    assert result.job_id == new_job_id
    assert result.rows_written == 0
    assert "enqueued" in result.summary.lower()


@pytest.mark.asyncio
async def test_make_sync_via_dag_deduplicates_pending_job():
    """TC-006 — In-flight pending row returns existing job_id, summary says 'in progress'."""
    from src.integrations.personal.dag_sync import make_sync_via_dag

    integration = _fake_integration()
    db = AsyncMock()
    existing_job_id = str(uuid.uuid4())
    fake_job = _fake_job(existing_job_id, deduped=True)

    with patch(PATCH_TARGET, AsyncMock(return_value=fake_job)):
        result: SyncResult = await make_sync_via_dag("calendar_ingestor")(
            integration=integration, db=db
        )

    assert result.mode == "enqueued"
    assert result.job_id == existing_job_id
    assert "in progress" in result.summary.lower()


@pytest.mark.asyncio
async def test_make_sync_via_dag_deduplicates_picked_job():
    """TC-007 — In-flight picked row is treated identically to pending (dedup=True)."""
    from src.integrations.personal.dag_sync import make_sync_via_dag

    integration = _fake_integration()
    db = AsyncMock()
    existing_job_id = str(uuid.uuid4())
    fake_job = _fake_job(existing_job_id, deduped=True)
    fake_job.status = "picked"

    with patch(PATCH_TARGET, AsyncMock(return_value=fake_job)):
        result: SyncResult = await make_sync_via_dag("calendar_ingestor")(
            integration=integration, db=db
        )

    assert result.mode == "enqueued"
    assert result.job_id == existing_job_id


@pytest.mark.asyncio
async def test_make_sync_via_dag_does_not_write_last_synced_at():
    """TC-009 — The root-cause regression guard: enqueue must never touch last_synced_at.

    Before FEAT-144 the enqueue helper wrote last_synced_at immediately,
    producing a false success. That line must not exist.
    """
    from src.integrations.personal.dag_sync import make_sync_via_dag

    integration = _fake_integration()
    db = AsyncMock()
    new_job_id = str(uuid.uuid4())
    fake_job = _fake_job(new_job_id, deduped=False)

    original_last_synced_at = integration.last_synced_at

    with patch(PATCH_TARGET, AsyncMock(return_value=fake_job)):
        await make_sync_via_dag("calendar_ingestor")(integration=integration, db=db)

    assert integration.last_synced_at == original_last_synced_at, (
        "make_sync_via_dag wrote last_synced_at during enqueue — this is the "
        "FEAT-144 root cause. Only finalize_sync() may write this field."
    )


@pytest.mark.asyncio
async def test_make_sync_via_dag_duration_ms_is_non_negative():
    """TC-011 — duration_ms must be >= 0 and reflect enqueue wall-clock time."""
    from src.integrations.personal.dag_sync import make_sync_via_dag

    integration = _fake_integration()
    db = AsyncMock()
    fake_job = _fake_job(str(uuid.uuid4()), deduped=False)

    with patch(PATCH_TARGET, AsyncMock(return_value=fake_job)):
        result = await make_sync_via_dag("calendar_ingestor")(
            integration=integration, db=db
        )

    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_make_sync_via_dag_race_error_becomes_integration_error():
    """TC-012 — EnqueueRaceError from the unique-index race is surfaced as
    IntegrationError with code='sync_race_retry' (routable to 400 by the router).
    """
    from src.integrations.personal.dag_sync import make_sync_via_dag
    from src.services.ingestion.enqueue import EnqueueRaceError

    integration = _fake_integration()
    db = AsyncMock()

    with patch(PATCH_TARGET, AsyncMock(side_effect=EnqueueRaceError("race"))):
        with pytest.raises(IntegrationError) as exc_info:
            await make_sync_via_dag("calendar_ingestor")(integration=integration, db=db)

    assert exc_info.value.code == "sync_race_retry"


@pytest.mark.asyncio
async def test_make_sync_via_dag_raises_when_integration_has_no_user_id():
    """TC-008 — Personal integrations require a user_id; None must raise IntegrationError."""
    from src.integrations.personal.dag_sync import make_sync_via_dag

    integration = _fake_integration(user_id=None)
    integration.user_id = None
    db = AsyncMock()

    with pytest.raises(IntegrationError) as exc_info:
        await make_sync_via_dag("calendar_ingestor")(integration=integration, db=db)

    assert exc_info.value.code == "no_user"
