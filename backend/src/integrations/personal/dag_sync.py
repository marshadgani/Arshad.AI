"""Enqueue-a-DAG sync implementation shared by the personal integrations.

Extracted from `_shared.py`: this has nothing to do with OAuth accounts,
scopes, or the attach flow — it is the sync half of the provider contract,
and the only reason it lived next to them was that the same six provider
modules happened to import both.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ..base import IntegrationError, SyncResult


def make_sync_via_dag(
    dag_id: str,
) -> Callable[..., Awaitable[SyncResult]]:
    """Returns an async sync() implementation that enqueues a Phase F
    DAG trigger row. Reuses the existing dag_trigger_queue table.

    FEAT-144: this function NEVER performs the real ingestion
    synchronously, and it NEVER touches Integration.last_synced_at or
    last_error — those are written exactly once, by
    services/ingestion/sync_completion.finalize_sync(), after the queue
    worker (Render) or Airflow (docker-compose) actually runs the
    ingestion. Returning mode='enqueued' here (rather than the old
    behaviour of writing last_synced_at immediately and calling it done)
    is what lets the router and the frontend distinguish "queued" from
    "done" instead of reporting a false success.
    """

    async def _sync(*, integration: Integration, db: AsyncSession) -> SyncResult:
        # Local import to avoid an integrations <-> services import cycle.
        from ...services.ingestion.enqueue import EnqueueRaceError, enqueue_dag_job

        if integration.user_id is None:
            raise IntegrationError(
                "no_user", "Personal integrations require a user_id."
            )
        started = time.perf_counter()

        # Dedup (an impatient double-click, a client retry, or a chat agent
        # racing the UI must not trigger the provider API twice) and the
        # uq_dag_trigger_queue_user_dag_inflight race it can lose are both
        # handled once, in enqueue_dag_job — every inserter of this table
        # needs that handling, not just this one.
        try:
            job = await enqueue_dag_job(
                db,
                dag_id=dag_id,
                user_id=integration.user_id,
                payload={"triggered_by": "integration_sync", "slug": integration.slug},
            )
        except EnqueueRaceError as exc:
            raise IntegrationError(
                "sync_race_retry",
                "Sync request conflicted with another in-flight sync; retry.",
            ) from exc

        return SyncResult(
            rows_written=0,
            summary="Sync already in progress." if job.deduped else "Sync enqueued.",
            duration_ms=int((time.perf_counter() - started) * 1000),
            mode="enqueued",
            job_id=job.job_id,
        )

    return _sync
