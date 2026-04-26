"""In-process queue worker — used on Render where Airflow doesn't run.

Polls dag_trigger_queue for pending rows, claims one with SELECT ...
FOR UPDATE SKIP LOCKED LIMIT 1, calls the ingestion runner, marks
completed/failed/retry. Started via FastAPI lifespan if
ENABLE_INPROCESS_WORKER=true.

In docker-compose dev, leave the env var false — Airflow handles the
queue. The SKIP LOCKED clause means it's safe to run both simultaneously
(though wasteful), so a misconfiguration won't double-process.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select

from ..models.dag_trigger import DagTriggerQueue
from ..models.database import AsyncSessionLocal
from .ingestion import runner as ingestion_runner

_log = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 5.0
_MAX_ATTEMPTS = 3


def _poll_interval() -> float:
    try:
        return max(0.5, float(os.getenv("QUEUE_POLL_INTERVAL_SECONDS", "5")))
    except ValueError:
        return _DEFAULT_POLL_INTERVAL


def is_enabled() -> bool:
    return os.getenv("ENABLE_INPROCESS_WORKER", "false").lower() == "true"


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


async def _process(row_id, dag_id: str, user_id, payload: dict, attempt: int) -> None:
    """Run the ingestion in a fresh session, then update the queue row."""
    async with AsyncSessionLocal() as runner_db:
        try:
            await ingestion_runner.run(
                dag_id=dag_id, user_id=user_id, payload=payload, db=runner_db
            )
            success = True
            error_text = None
        except Exception as exc:  # noqa: BLE001 — surface ALL errors as failed
            _log.warning("queue worker run failed dag=%s err=%r", dag_id, exc)
            success = False
            error_text = f"{type(exc).__name__}: {exc}"

    async with AsyncSessionLocal() as status_db:
        async with status_db.begin():
            row = await status_db.scalar(
                select(DagTriggerQueue).where(DagTriggerQueue.id == row_id)
            )
            if row is None:
                return
            if success:
                row.status = "completed"
                row.completed_at = datetime.now(timezone.utc)
                row.error_text = None
            else:
                row.error_text = error_text
                if attempt >= _MAX_ATTEMPTS:
                    row.status = "failed"
                    row.completed_at = datetime.now(timezone.utc)
                else:
                    row.status = "pending"  # next poll picks it up again


async def run_worker(stop_event: asyncio.Event) -> None:
    base_interval = _poll_interval()
    backoff = base_interval
    _log.info("queue worker started poll_interval=%s", base_interval)
    while not stop_event.is_set():
        claim_failed = False
        try:
            row = await _claim_one()
        except Exception as exc:  # noqa: BLE001 — DB transient errors should retry
            _log.warning("queue worker claim failed err=%r backoff=%s", exc, backoff)
            row = None
            claim_failed = True

        if row is not None:
            backoff = base_interval  # successful claim resets backoff
            await _process(row.id, row.dag_id, row.user_id, row.payload, row.attempt)
            continue  # loop hot — there may be more work

        # If the claim itself failed (DB connection drop, etc.), grow backoff
        # exponentially up to 5 minutes so a sick DB doesn't get hammered.
        # Successful empty-queue polls keep base_interval.
        if claim_failed:
            backoff = min(backoff * 2, 300)
            wait_for = backoff
        else:
            wait_for = base_interval

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_for)
        except asyncio.TimeoutError:
            pass
    _log.info("queue worker stopped")
