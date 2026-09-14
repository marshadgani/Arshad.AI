"""drainer — WHO is expected to drain dag_trigger_queue, and is it alive?

Kept separate from `worker.py` so the read path (`sync_jobs`, behind
GET /{slug}/sync/status and GET /api/v1/obsidian/sync/status) can ask "is a
drainer alive?" without importing the polling loop — and through it the
whole ingestion runner — into the request path.

Environment contract (FEAT-144):
  ENABLE_INPROCESS_WORKER=true  → this process runs the worker (Render).
  QUEUE_DRAINER=airflow         → Airflow drains it (docker-compose dev).
  neither                       → nothing drains it; rows sit pending
                                  forever and `is_drained()` is False, so
                                  the UI says "stalled" instead of lying.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from ...middleware.cache import get_redis

_log = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 5.0

# Redis key the worker refreshes every loop iteration. TTL expiry IS the
# liveness signal — no separate "stopped cleanly" write is needed.
_HEARTBEAT_KEY = "queue_worker:heartbeat"


@dataclass(frozen=True)
class DrainerLiveness:
    """What the status endpoints know about the drainer at one instant.

    enabled: something is expected to drain the queue at all.
    alive:   True/False from a real heartbeat, or None when liveness
             cannot be observed (Airflow drains it, or Redis is
             unreachable). None means "unknown", never "not alive" —
             see sync_status.derive_job_view's worker_alive semantics.
    """

    enabled: bool
    alive: bool | None


def poll_interval() -> float:
    try:
        return max(0.5, float(os.getenv("QUEUE_POLL_INTERVAL_SECONDS", "5")))
    except ValueError:
        return DEFAULT_POLL_INTERVAL


def is_enabled() -> bool:
    """True if THIS process should run the in-process worker."""
    return os.getenv("ENABLE_INPROCESS_WORKER", "false").lower() == "true"


def is_drained() -> bool:
    """True if *something* is expected to drain dag_trigger_queue at all —
    the in-process worker (Render), or Airflow (docker-compose dev, where
    ENABLE_INPROCESS_WORKER is deliberately left false and QUEUE_DRAINER=
    airflow instead). Distinct from is_enabled() alone so a healthy
    Airflow-backed dev environment doesn't get a false "stalled:
    no_worker_running" verdict from sync_status.derive_job_view."""
    if is_enabled():
        return True
    return os.getenv("QUEUE_DRAINER", "").strip().lower() == "airflow"


async def publish_heartbeat(interval: float) -> None:
    try:
        redis = await get_redis()
        ttl = int(max(30, interval * 3))
        await redis.set(_HEARTBEAT_KEY, datetime.now(timezone.utc).isoformat(), ex=ttl)
    except Exception as exc:  # noqa: BLE001 — heartbeat is best-effort
        # Best-effort does not mean invisible: a Redis outage here means
        # worker_alive silently degrades to None ("unknown") for every
        # /sync/status poll, which sync_status.derive_job_view treats as
        # "processing" rather than "stalled" — a real production problem
        # masked as normal. This must log at a level the deployment
        # verification protocol (CLAUDE.md §23, which greps only
        # error/critical/warning) will actually surface.
        _log.warning("queue worker heartbeat publish failed: %r", exc)


async def heartbeat_alive() -> bool | None:
    """True/False if Redis answered the liveness check; None ("unknown")
    if Redis itself is unreachable. Unknown must never be treated as
    "not alive" by callers — see sync_status.derive_job_view's worker_alive
    semantics."""
    try:
        redis = await get_redis()
        return bool(await redis.exists(_HEARTBEAT_KEY))
    except Exception:  # noqa: BLE001
        return None


async def observe() -> DrainerLiveness:
    """The one composition of "enabled?" + "alive?" in the codebase.

    The `if is_enabled()` guard is load-bearing: it keeps an Airflow-drained
    environment (which publishes no heartbeat) reporting alive=None
    (unknown) rather than alive=False, which derive_job_view reads as a
    stall.
    """
    return DrainerLiveness(
        enabled=is_drained(),
        alive=await heartbeat_alive() if is_enabled() else None,
    )
