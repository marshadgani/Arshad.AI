"""In-process queue worker — used on Render where Airflow doesn't run.

Polls dag_trigger_queue for pending rows, claims one with SELECT ...
FOR UPDATE SKIP LOCKED LIMIT 1, calls the ingestion runner, marks
completed/failed/retry. Started via FastAPI lifespan when
drainer.is_enabled() (ENABLE_INPROCESS_WORKER=true).

In docker-compose dev, leave the env var false — Airflow handles the
queue. The SKIP LOCKED clause means it's safe to run both simultaneously
(though wasteful), so a misconfiguration won't double-process.

Deployment policy and the liveness heartbeat live in `drainer.py`; this
module is only the loop. See that module's docstring for why.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ...models.dag_trigger import DagTriggerQueue
from ...models.database import AsyncSessionLocal
from ..ingestion import runner as ingestion_runner
from . import drainer

_log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3

# Grow the backoff no further than this when the DB itself is sick.
_MAX_BACKOFF_SECONDS = 300


async def _claim_one() -> DagTriggerQueue | None:
    """Atomically claim the next pending row.

    Returns the row (already updated to status='picked' and committed) or
    None if no pending work exists.
    """
    async with AsyncSessionLocal() as db:
        async with db.begin():
            row = await db.scalar(
                select(DagTriggerQueue)
                .where(DagTriggerQueue.status == "pending")
                .order_by(DagTriggerQueue.requested_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            row.status = "picked"
            row.picked_at = datetime.now(timezone.utc)
            row.attempt = (row.attempt or 0) + 1
            db.add(row)
        await db.refresh(row)
        return row


async def _run_ingestion(
    *, dag_id: str, user_id: uuid.UUID, payload: dict[str, Any]
) -> str | None:
    """Run one ingestion. Returns None on success, or the error text.

    Errors become a value rather than an exception because the caller's
    job is bookkeeping, not error handling: every failure mode — expected
    IngestionError or not — lands in dag_trigger_queue.error_text the same
    way.
    """
    async with AsyncSessionLocal() as db:
        try:
            await ingestion_runner.run(
                dag_id=dag_id, user_id=user_id, payload=payload, db=db
            )
        except Exception as exc:  # noqa: BLE001 — surface ALL errors as failed
            _log.warning("queue worker run failed dag=%s err=%r", dag_id, exc)
            return f"{type(exc).__name__}: {exc}"
    return None


async def _record_outcome(
    *, row_id: uuid.UUID, error_text: str | None, attempt: int
) -> None:
    """Write the terminal (or retryable) state back onto the queue row."""
    async with AsyncSessionLocal() as db:
        async with db.begin():
            row = await db.scalar(
                select(DagTriggerQueue).where(DagTriggerQueue.id == row_id)
            )
            if row is None:
                # The row we claimed and ran vanished before its outcome
                # could be written back. Returning silently would drop the
                # ingestion result — error_text included — with zero trace,
                # which is exactly the dishonesty FEAT-144 exists to end.
                _log.warning(
                    "queue worker: dag_trigger_queue row %s vanished before "
                    "outcome could be recorded (error_text=%r, attempt=%s)",
                    row_id,
                    error_text,
                    attempt,
                )
                return
            if error_text is None:
                row.status = "completed"
                row.completed_at = datetime.now(timezone.utc)
                row.error_text = None
            else:
                row.error_text = error_text
                if attempt >= _MAX_ATTEMPTS:
                    row.status = "failed"
                    row.completed_at = datetime.now(timezone.utc)
                    _log.warning(
                        "queue worker: job %s (dag=%s) permanently failed "
                        "after %s attempts: %s",
                        row_id,
                        row.dag_id,
                        attempt,
                        error_text,
                    )
                else:
                    row.status = "pending"  # next poll picks it up again


async def run_worker(stop_event: asyncio.Event) -> None:
    base_interval = drainer.poll_interval()
    backoff = base_interval
    _log.info("queue worker started poll_interval=%s", base_interval)
    while not stop_event.is_set():
        await drainer.publish_heartbeat(base_interval)
        claim_failed = False
        try:
            row = await _claim_one()
        except Exception as exc:  # noqa: BLE001 — DB transient errors should retry
            _log.warning("queue worker claim failed err=%r backoff=%s", exc, backoff)
            row = None
            claim_failed = True

        if row is not None:
            backoff = base_interval  # successful claim resets backoff
            row_id, attempt = row.id, row.attempt
            error_text = await _run_ingestion(
                dag_id=row.dag_id, user_id=row.user_id, payload=row.payload
            )
            await _record_outcome(row_id=row_id, error_text=error_text, attempt=attempt)
            continue  # loop hot — there may be more work

        # If the claim itself failed (DB connection drop, etc.), grow backoff
        # exponentially up to 5 minutes so a sick DB doesn't get hammered.
        # Successful empty-queue polls keep base_interval.
        if claim_failed:
            backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
            wait_for = backoff
        else:
            wait_for = base_interval

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=wait_for)
    _log.info("queue worker stopped")
