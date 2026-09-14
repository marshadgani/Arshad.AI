"""TC-057 through TC-061 — enqueue_dag_job dedup and race-recovery unit tests.

REQUIREMENTS COVERED:
  REQ-T57  No in-flight row → inserts new row, returns deduped=False
  REQ-T58  In-flight row exists before INSERT → returns existing row, deduped=True
  REQ-T59  IntegrityError on INSERT, winner still in-flight → returns winner, deduped=True
  REQ-T60  IntegrityError on INSERT, winner already completed → raises EnqueueRaceError on 2nd attempt
  REQ-T61  EnqueuedJob is a frozen dataclass (immutable)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from src.services.ingestion.enqueue import (
    EnqueuedJob,
    EnqueueRaceError,
    enqueue_dag_job,
)


def _make_queue_row(job_id=None, status="pending"):
    row = MagicMock()
    row.id = job_id or uuid.uuid4()
    row.status = status
    return row


@pytest.mark.asyncio
async def test_enqueue_dag_job_inserts_when_no_in_flight():
    """TC-057 — No in-flight row: inserts, returns deduped=False."""
    user_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # no in-flight row
    db.add = MagicMock()
    db.commit = AsyncMock()

    result = await enqueue_dag_job(
        db, dag_id="calendar_ingestor", user_id=user_id, payload={}
    )

    assert result.deduped is False
    assert result.status == "pending"
    assert isinstance(result.job_id, str)
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_dag_job_deduplicates_when_in_flight_row_exists():
    """TC-058 — Existing in-flight row found → reuses it, no INSERT."""
    user_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    existing_row = _make_queue_row(job_id=existing_id, status="pending")

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=existing_row)
    db.add = MagicMock()

    result = await enqueue_dag_job(
        db, dag_id="calendar_ingestor", user_id=user_id, payload={}
    )

    assert result.deduped is True
    assert result.job_id == str(existing_id)
    db.add.assert_not_called()  # no INSERT attempted


@pytest.mark.asyncio
async def test_enqueue_dag_job_recovers_from_integrity_error_with_winner():
    """TC-059 — Unique index race: INSERT raises IntegrityError, winner is found."""
    user_id = uuid.uuid4()
    winner_id = uuid.uuid4()
    winner_row = _make_queue_row(job_id=winner_id, status="picked")

    db = AsyncMock()
    # First scalar call (pre-INSERT check): no row; second (recovery): winner
    db.scalar = AsyncMock(side_effect=[None, winner_row])
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=[IntegrityError(None, None, None), None])
    db.rollback = AsyncMock()

    result = await enqueue_dag_job(
        db, dag_id="calendar_ingestor", user_id=user_id, payload={}
    )

    assert result.deduped is True
    assert result.job_id == str(winner_id)
    db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_dag_job_raises_race_error_when_winner_disappears():
    """TC-060 — Unique-index race with winner already finished: EnqueueRaceError after 2nd attempt."""
    user_id = uuid.uuid4()

    db = AsyncMock()
    # All scalar calls return None (no winner in-flight)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=IntegrityError(None, None, None))
    db.rollback = AsyncMock()

    with pytest.raises(EnqueueRaceError):
        await enqueue_dag_job(
            db, dag_id="calendar_ingestor", user_id=user_id, payload={}
        )


def test_enqueued_job_is_frozen():
    """TC-061 — EnqueuedJob is a frozen dataclass (immutable after construction)."""
    job = EnqueuedJob(job_id="abc", status="pending", deduped=False)
    with pytest.raises((AttributeError, TypeError)):
        job.job_id = "mutated"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_enqueue_dag_job_scopes_in_flight_check_by_user_id_and_dag_id():
    """TC-062 — _find_in_flight is invoked with the caller's user_id and dag_id, not
    just one of them (a same-dag job for a different user must not be reused)."""
    from unittest.mock import patch

    user_id = uuid.uuid4()
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch(
        "src.services.ingestion.enqueue._find_in_flight", AsyncMock(return_value=None)
    ) as mock_find:
        await enqueue_dag_job(db, dag_id="email_ingestor", user_id=user_id, payload={})

    mock_find.assert_called_once_with(db, dag_id="email_ingestor", user_id=user_id)
