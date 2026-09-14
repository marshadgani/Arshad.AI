"""Ownership boundary for the dag_trigger_queue table (FEAT-144).

Before this module, three unrelated layers each spoke SQL to
dag_trigger_queue directly:

  - integrations/personal/_shared.py  — advisory lock + dedupe + INSERT,
    reaching across the integrations boundary into a queue table via a
    function-local import specifically to dodge an import cycle (the
    classic sign that code lives in the wrong module).
  - integrations/routers.py           — an HTTP route hand-writing a
    "latest job for (user, dag)" SELECT.
  - api/v1/obsidian.py                — a second HTTP route hand-writing
    the same SELECT, plus its own INSERT.

Three copies of one contract is how the dedupe rule, the lease window,
and the "always filter by user_id" security predicate drift apart. Every
enqueue and every point-read now goes through this module; the only
other legitimate reader is services/queue_worker.py, which owns the
claim loop (SELECT ... FOR UPDATE SKIP LOCKED) and is a different
concern entirely.

This module deliberately knows nothing about integrations, providers, or
HTTP: it raises its own EnqueueConflict rather than IntegrationError, and
returns rows/outcomes rather than wire shapes. Callers translate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.dag_trigger import DagTriggerQueue

# A row claimed by the worker (status='picked') but never completed —
# e.g. the process was killed mid-ingest on a Render restart — must not
# permanently block new enqueues. 10 minutes comfortably exceeds any
# single ingest run; past that a 'picked' row is treated as dead for
# dedupe purposes (the worker itself remains the source of truth for
# actually marking it failed).
PICKED_LEASE_SECONDS = 600


class EnqueueConflict(Exception):
    """Two concurrent enqueues raced and this one lost, and the winning
    row was already claimed by a worker before it could be reported back.

    Nothing was enqueued for this caller and there is no live job to
    point at, so retrying is the only correct response. Callers translate
    this into whatever their layer's error vocabulary is (the
    integrations layer maps it to IntegrationError('sync_enqueue_conflict')).
    """


@dataclass(frozen=True)
class EnqueueOutcome:
    """Result of enqueue_deduped().

    deduped=True means no new row was written — job_id refers to a job
    that was already live for this (user, dag_id). Callers must not
    describe this as a freshly started sync.
    """

    job_id: str
    dag_id: str
    deduped: bool


def _advisory_lock_key(user_id: uuid.UUID, dag_id: str) -> str:
    return f"dag_trigger_queue:{user_id}:{dag_id}"


async def _lock_live_job(
    db: AsyncSession, *, user_id: uuid.UUID, dag_id: str
) -> DagTriggerQueue | None:
    """The newest job for (user, dag_id) that still counts as in flight —
    'pending', or 'picked' within PICKED_LEASE_SECONDS — locked FOR UPDATE."""
    picked_lease_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=PICKED_LEASE_SECONDS
    )
    return await db.scalar(
        select(DagTriggerQueue)
        .where(
            DagTriggerQueue.user_id == user_id,
            DagTriggerQueue.dag_id == dag_id,
            (DagTriggerQueue.status == "pending")
            | (
                (DagTriggerQueue.status == "picked")
                & (DagTriggerQueue.picked_at > picked_lease_cutoff)
            ),
        )
        .order_by(DagTriggerQueue.requested_at.desc())
        .limit(1)
        .with_for_update()
    )


async def enqueue_deduped(
    db: AsyncSession,
    *,
    dag_id: str,
    user_id: uuid.UUID,
    payload: dict[str, Any],
) -> EnqueueOutcome:
    """Enqueue one DAG trigger, collapsing duplicates.

    Idempotent: if a live job for this (user, dag_id) already exists —
    status='pending', or status='picked' within PICKED_LEASE_SECONDS —
    that job's id is returned instead of enqueuing a duplicate. This
    guards against replay storms (e.g. a user double-clicking "Sync now")
    without needing a reaper process.

    Concurrency note: the check-existing-then-insert sequence below is a
    classic TOCTOU race — two requests hitting this function at nearly
    the same instant can both see no existing row and both insert one,
    since a SELECT (even ``FOR UPDATE``) locks nothing when it matches no
    rows. A Postgres transaction-scoped advisory lock keyed on
    (user_id, dag_id) closes that window: the second concurrent caller
    blocks until the first commits, then sees the row it just inserted
    and dedupes against it. The lock is released automatically at
    transaction end (commit or rollback) — no separate unlock call needed.

    The partial unique index uq_dag_trigger_queue_pending_user_dag is the
    hard safety net underneath the advisory lock (it also covers callers
    on a different connection pool, or a future second process), so the
    IntegrityError path below is a supported outcome, not an anomaly.

    Raises EnqueueConflict when this caller lost that race AND the winner
    is no longer pending — nothing was enqueued and there is no live job
    to report.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": _advisory_lock_key(user_id, dag_id)},
    )

    existing = await _lock_live_job(db, user_id=user_id, dag_id=dag_id)
    if existing is not None:
        return EnqueueOutcome(job_id=str(existing.id), dag_id=dag_id, deduped=True)

    row = DagTriggerQueue(dag_id=dag_id, user_id=user_id, payload=payload)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race against a concurrent enqueue: the SELECT ... FOR
        # UPDATE above only locks rows that already exist, so two
        # concurrent callers can both see "no pending job" and both reach
        # this insert. The partial unique index lets exactly one of them
        # win; the loser rolls back and folds into the same dedupe
        # outcome the early return above would have given.
        await db.rollback()
        winner = await db.scalar(
            select(DagTriggerQueue)
            .where(
                DagTriggerQueue.user_id == user_id,
                DagTriggerQueue.dag_id == dag_id,
                DagTriggerQueue.status == "pending",
            )
            .order_by(DagTriggerQueue.requested_at.desc())
            .limit(1)
        )
        if winner is None:
            # The winning row was already picked up by a worker between
            # our rollback and this re-query — nothing pending left to
            # report, but the insert genuinely didn't happen for us.
            raise EnqueueConflict(dag_id) from None
        return EnqueueOutcome(job_id=str(winner.id), dag_id=dag_id, deduped=True)

    await db.refresh(row)
    return EnqueueOutcome(job_id=str(row.id), dag_id=dag_id, deduped=False)


async def enqueue(
    db: AsyncSession,
    *,
    dag_id: str,
    user_id: uuid.UUID,
    payload: dict[str, Any],
) -> DagTriggerQueue:
    """Unconditional enqueue — always writes a new row.

    Used by callers that have no dedupe requirement (the Obsidian vault
    sync). Kept here rather than inlined at the call site so that every
    write to dag_trigger_queue still passes through this one module.
    """
    row = DagTriggerQueue(
        id=uuid.uuid4(),
        dag_id=dag_id,
        user_id=user_id,
        payload=payload,
        status="pending",
        requested_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    return row


async def latest_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    dag_id: str,
    job_id: uuid.UUID | None = None,
) -> DagTriggerQueue | None:
    """The most recent job for (user, dag_id), optionally narrowed to one id.

    user_id is always part of the predicate and job_id is only ever AND'd
    onto it — never a replacement for it — so a caller can never reach
    another user's job by guessing an id. Centralising the query is what
    keeps that guarantee from having to be re-established (and re-reviewed)
    at every polling endpoint.
    """
    stmt = select(DagTriggerQueue).where(
        DagTriggerQueue.user_id == user_id,
        DagTriggerQueue.dag_id == dag_id,
    )
    if job_id is not None:
        stmt = stmt.where(DagTriggerQueue.id == job_id)
    stmt = stmt.order_by(DagTriggerQueue.requested_at.desc()).limit(1)
    return await db.scalar(stmt)
