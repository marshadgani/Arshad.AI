"""sync_jobs — the READ side of dag_trigger_queue.

`enqueue.py` owns writes to this table; this module owns the lookups behind
GET /api/v1/integrations/{slug}/sync/status and GET /api/v1/obsidian/
sync/status, so neither router touches DagTriggerQueue directly. That is
security-relevant, not just tidiness: the `user_id` scoping below is what
stops one user polling another's job_id, and a scoping rule enforced in two
routers is one that can drift in one of them.

Deliberately leaves job_id *parsing* to the routers — "is this string a
UUID?" is request validation (422), not a queue concern.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dag_trigger import DagTriggerQueue
from ..queue import drainer
from .sync_status import KNOWN_STATUSES, derive_job_view

_log = logging.getLogger(__name__)

__all__ = ["find_job", "job_status_view"]


async def find_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    dag_id: str,
    job_id: uuid.UUID | None = None,
) -> DagTriggerQueue | None:
    """One queue row for this user and DAG.

    Always scoped by user_id AND dag_id, even when job_id is given: a
    job_id belonging to another user (or another provider) must come back
    as None — a miss — rather than leaking that it exists.

    Without job_id, falls back to the most recent job for the pair, which
    is what makes the polling UI survive a page reload that lost the id.
    """
    stmt = select(DagTriggerQueue).where(
        DagTriggerQueue.user_id == user_id,
        DagTriggerQueue.dag_id == dag_id,
    )
    if job_id is not None:
        stmt = stmt.where(DagTriggerQueue.id == job_id)
    else:
        stmt = stmt.order_by(DagTriggerQueue.requested_at.desc()).limit(1)
    return await db.scalar(stmt)


def _view_of(row: DagTriggerQueue, liveness: drainer.DrainerLiveness) -> dict[str, Any]:
    """Adapt one ORM row + liveness into derive_job_view's pure inputs."""
    if row.status not in KNOWN_STATUSES:
        # derive_job_view is deliberately pure, so it silently defaults an
        # unrecognised status to "processing" — which on the polling UI is
        # indistinguishable from healthy progress. An unexpected status is
        # a data-integrity problem (bad write path, typo'd status string,
        # manual DB surgery) that deserves a trace, and this is the only
        # caller holding the row, so it is the only place that can log it.
        _log.warning(
            "sync job %s (dag=%s, user=%s) has unrecognised status %r — "
            "reporting as 'processing'; investigate how this was written",
            row.id,
            row.dag_id,
            row.user_id,
            row.status,
        )
    return derive_job_view(
        job_id=str(row.id),
        status=row.status,
        requested_at=row.requested_at,
        picked_at=row.picked_at,
        completed_at=row.completed_at,
        error_text=row.error_text,
        attempt=row.attempt,
        worker_enabled=liveness.enabled,
        worker_alive=liveness.alive,
    )


async def job_status_view(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    dag_id: str,
    job_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """The whole read use case: find the job, observe the drainer, derive
    the UI-facing view. None when no such job exists — callers decide
    whether that is a 404 or a null body.
    """
    row = await find_job(db, user_id=user_id, dag_id=dag_id, job_id=job_id)
    if row is None:
        return None
    return _view_of(row, await drainer.observe())
