"""DagTriggerQueue plumbing for the Obsidian sync and export DAGs.

Both DAGs are queued and reported the same way, so the row shape and the
wire shape live here once and the router never touches the queue table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dag_trigger import DagTriggerQueue
from ...models.user import User

INGEST_DAG_ID = "obsidian_ingestor"
EXPORT_DAG_ID = "obsidian_exporter"


async def enqueue(
    db: AsyncSession,
    user: User,
    dag_id: str,
    payload: dict[str, Any],
    requested_at: datetime | None = None,
) -> DagTriggerQueue:
    """Queue a DAG run for this user and commit it."""
    job = DagTriggerQueue(
        id=uuid.uuid4(),
        dag_id=dag_id,
        user_id=user.id,
        payload=payload,
        status="pending",
        requested_at=requested_at or datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    return job


async def latest_job(
    db: AsyncSession, user: User, dag_id: str
) -> DagTriggerQueue | None:
    """The most recently requested run of `dag_id` for this user."""
    return await db.scalar(
        select(DagTriggerQueue)
        .where(DagTriggerQueue.user_id == user.id, DagTriggerQueue.dag_id == dag_id)
        .order_by(DagTriggerQueue.requested_at.desc())
        .limit(1)
    )


def job_summary(job: DagTriggerQueue) -> dict[str, Any]:
    """The wire shape both /sync/status and /export/status return."""
    return {
        "job_id": str(job.id),
        "status": job.status,
        "requested_at": job.requested_at.isoformat() if job.requested_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error": job.error_text,
    }


__all__ = [
    "EXPORT_DAG_ID",
    "INGEST_DAG_ID",
    "enqueue",
    "job_summary",
    "latest_job",
]
