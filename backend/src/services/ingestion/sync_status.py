"""sync_status — pure derivation of a dag_trigger_queue row into a UI-facing
progress view (FEAT-144).

Single definition shared by integrations/routers.py's GET /{slug}/sync/status
and api/v1/obsidian.py's GET /sync/status, so "stalled" has exactly one
meaning across the app instead of two endpoints inventing their own
thresholds independently. Deliberately pure and side-effect-free — no DB
access, no clock reads unless `now` is omitted — so it is fully covered by
table-driven unit tests without a database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

Progress = Literal["processing", "completed", "failed", "stalled"]
StalledReason = Literal["no_worker_running", "worker_not_responding", "worker_timeout"]

# dag_trigger_queue.status values this module actually knows how to
# interpret. Exposed so callers that hold the ORM row (sync_jobs._view_of)
# can log an unrecognised value before handing it to derive_job_view, which
# is deliberately pure and must not log — see derive_job_view's docstring
# and its own "unrecognised status" branch below.
KNOWN_STATUSES = frozenset({"pending", "picked", "completed", "failed"})

# A row picked more than this long ago with no completion is treated as
# stuck rather than merely slow — long enough to tolerate a real backfill,
# short enough to surface a genuinely wedged worker within one session.
PICKED_STALL_AFTER = timedelta(minutes=15)

# A pending row younger than this is "processing" even if the worker
# heartbeat looks absent — avoids a false "stalled" flash in the first
# couple of poll cycles after enqueue, before the worker has had a chance
# to claim it.
PENDING_NO_HEARTBEAT_GRACE = timedelta(seconds=60)


def _as_utc(value: datetime | None) -> datetime | None:
    """Legacy rows (and any caller who forgets tz-awareness) may carry a
    naive datetime. Treat naive as UTC instead of raising TypeError on the
    subtraction below — the whole app stores wall-clock time in UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def derive_job_view(
    *,
    job_id: str,
    status: str,
    requested_at: datetime | None,
    picked_at: datetime | None,
    completed_at: datetime | None,
    error_text: str | None,
    attempt: int,
    worker_enabled: bool,
    worker_alive: bool | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive {progress, stalled_reason, retrying, ...} from one
    dag_trigger_queue row plus worker liveness.

    worker_enabled: True if *something* is expected to drain the queue at
        all (the in-process worker on Render, or Airflow in docker-compose
        dev — see services.queue.drainer.is_drained()). False means the row will sit
        pending forever and the client should stop polling immediately.
    worker_alive: True/False from a real Redis heartbeat when the
        in-process worker is the drainer, or None ("unknown") when
        liveness can't be observed (Airflow, or Redis itself unreachable).
        Unknown liveness must never manufacture a "stalled" verdict — an
        absent heartbeat is only evidence of trouble when we know a
        heartbeat *should* exist.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    requested_at = _as_utc(requested_at)
    picked_at = _as_utc(picked_at)
    completed_at = _as_utc(completed_at)

    progress: Progress
    stalled_reason: StalledReason | None = None
    retrying = False

    if status == "completed":
        progress = "completed"
    elif status == "failed":
        progress = "failed"
    elif status == "picked":
        if picked_at is not None and (now - picked_at) > PICKED_STALL_AFTER:
            progress = "stalled"
            stalled_reason = "worker_timeout"
        else:
            progress = "processing"
    elif status == "pending":
        age = (now - requested_at) if requested_at is not None else timedelta(0)
        if worker_enabled is False:
            # Nothing will ever drain this row — say so immediately rather
            # than waiting out a grace period that can't help.
            progress = "stalled"
            stalled_reason = "no_worker_running"
        elif worker_alive is False and age > PENDING_NO_HEARTBEAT_GRACE:
            progress = "stalled"
            stalled_reason = "worker_not_responding"
        else:
            progress = "processing"
            retrying = attempt > 0 and error_text is not None
    else:
        # An unrecognised status value is a data problem to investigate,
        # not a reason to crash the status endpoint or the polling UI.
        progress = "processing"

    return {
        "job_id": job_id,
        "status": status,
        "progress": progress,
        "stalled_reason": stalled_reason,
        "retrying": retrying,
        "attempt": attempt,
        "worker_enabled": worker_enabled,
        "worker_alive": worker_alive,
        "error_text": error_text,
        "requested_at": requested_at.isoformat() if requested_at else None,
        "picked_at": picked_at.isoformat() if picked_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
    }
