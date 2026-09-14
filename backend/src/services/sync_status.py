"""Shared job-status projection for DagTriggerQueue rows (FEAT-144).

One function, consumed by both integrations/routers.py (GET
/{slug}/sync/status) and api/v1/obsidian.py (GET /obsidian/sync/status),
so the two pollable-sync surfaces in the app can never drift into two
different status vocabularies.

Depends on the worker only through a WorkerHealth snapshot, never on the
worker's internals — see services/worker_health.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import queue_worker
from .worker_health import WorkerHealth

# A 'pending' row this old, with the worker disabled or its heartbeat
# stale, is reported as 'stalled' instead of leaving the user staring at
# a spinner forever with no explanation.
STALE_THRESHOLD_SECONDS = 60
# How long the in-process worker's heartbeat may go quiet before it's
# treated as not actually polling (crashed task, deadlocked loop, etc.)
# even though ENABLE_INPROCESS_WORKER=true.
HEARTBEAT_STALE_SECONDS = 60

WORKER_DISABLED_MESSAGE = (
    "Sync is queued but the background worker is not running — "
    "set ENABLE_INPROCESS_WORKER=true on Render."
)
WORKER_NOT_POLLING_MESSAGE = "Sync is queued but the background worker is not polling."


def _stall_message(
    *, age_seconds: float, health: WorkerHealth, now: datetime
) -> str | None:
    """Why a still-'pending' job should be shown as stalled, or None if it
    is simply young enough to still be waiting its turn.

    Isolated from project_job so the 'when do we stop pretending this is
    fine' rule reads as one thing rather than as branches interleaved
    with dict-building.
    """
    if age_seconds <= STALE_THRESHOLD_SECONDS:
        return None
    if not health.enabled:
        return WORKER_DISABLED_MESSAGE
    if health.heartbeat_is_stale(now=now, threshold_seconds=HEARTBEAT_STALE_SECONDS):
        return WORKER_NOT_POLLING_MESSAGE
    return None


def project_job(
    row: Any,
    *,
    now: datetime | None = None,
    health: WorkerHealth | None = None,
) -> dict[str, Any]:
    """row is a DagTriggerQueue instance. Returns the wire shape shared by
    every sync-status endpoint in the app.

    now/health are injectable so the projection can be exercised without
    a clock or a running worker; both default to the live values."""
    now = now or datetime.now(timezone.utc)
    health = health or queue_worker.health()

    status = row.status
    message: str | None = None

    if status == "pending":
        age = (now - row.requested_at).total_seconds() if row.requested_at else 0
        message = _stall_message(age_seconds=age, health=health, now=now)
        if message is not None:
            status = "stalled"

    return {
        "job_id": str(row.id),
        "dag_id": row.dag_id,
        "status": status,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "picked_at": row.picked_at.isoformat() if row.picked_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "attempt": row.attempt,
        "error": row.error_text,
        "message": message,
    }
