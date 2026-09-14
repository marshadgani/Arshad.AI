"""enqueue_dag_job — the single, safe way to put a row into dag_trigger_queue.

FEAT-144 added the partial UNIQUE index uq_dag_trigger_queue_user_dag_inflight
on (user_id, dag_id) WHERE status IN ('pending', 'picked'). That constraint
applies to EVERY inserter of this table, not just the integrations sync path
that motivated it: the four data_pipeline agents and POST /api/v1/obsidian/sync
insert the same (user_id, dag_id) shape, so once a job is in flight their next
INSERT raises IntegrityError. Unhandled, that surfaces as a 500 carrying a raw
SQL constraint message — which .claude/rules/api.md forbids — instead of the
idempotent "you already have this job queued" answer the dedup rule intends.

Centralising the dedup SELECT + INSERT + IntegrityError recovery here means
the constraint has exactly one handler rather than one per call site.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dag_trigger import DagTriggerQueue

IN_FLIGHT_STATUSES = ("pending", "picked")


class EnqueueRaceError(RuntimeError):
    """The INSERT lost the unique-index race, and the job that won it had
    already completed by the time we looked for it — so there is neither a
    new row nor an in-flight one to hand back. Rare enough to be worth
    surfacing to the caller as a retryable conflict rather than silently
    reporting success for a row that was never written."""


@dataclass(frozen=True)
class EnqueuedJob:
    job_id: str
    status: str
    #: True when an equivalent job was already in flight and is being
    #: reused, False when this call actually wrote a new row.
    deduped: bool


async def _find_in_flight(
    db: AsyncSession, *, dag_id: str, user_id: uuid.UUID
) -> DagTriggerQueue | None:
    return await db.scalar(
        select(DagTriggerQueue)
        .where(
            DagTriggerQueue.user_id == user_id,
            DagTriggerQueue.dag_id == dag_id,
            DagTriggerQueue.status.in_(IN_FLIGHT_STATUSES),
        )
        .order_by(DagTriggerQueue.requested_at.desc())
        .limit(1)
    )


async def enqueue_dag_job(
    db: AsyncSession,
    *,
    dag_id: str,
    user_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> EnqueuedJob:
    """Enqueue one dag_trigger_queue row, reusing any job already in flight.

    Raises EnqueueRaceError only in the narrow case described on that class.
    """
    existing = await _find_in_flight(db, dag_id=dag_id, user_id=user_id)
    if existing is not None:
        return EnqueuedJob(
            job_id=str(existing.id), status=existing.status, deduped=True
        )

    # The SELECT above and this INSERT are not one atomic statement, so a
    # concurrent request (double-click, client retry, agent call racing a UI
    # sync) can still win. The partial unique index turns that into an
    # IntegrityError here instead of a second silent enqueue; one retry
    # covers the case where the winner finished in between.
    for attempt in range(2):
        job_id = uuid.uuid4()
        db.add(
            DagTriggerQueue(
                id=job_id,
                dag_id=dag_id,
                user_id=user_id,
                payload=payload or {},
                status="pending",
                requested_at=datetime.now(timezone.utc),
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            winner = await _find_in_flight(db, dag_id=dag_id, user_id=user_id)
            if winner is not None:
                return EnqueuedJob(
                    job_id=str(winner.id), status=winner.status, deduped=True
                )
            if attempt == 0:
                continue  # winner already finished — the queue is free again
            raise EnqueueRaceError(
                f"Could not enqueue {dag_id} for user {user_id}: "
                "conflicting in-flight job vanished twice."
            ) from None
        return EnqueuedJob(job_id=str(job_id), status="pending", deduped=False)

    raise EnqueueRaceError(f"Could not enqueue {dag_id} for user {user_id}.")
