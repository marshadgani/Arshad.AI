"""Liveness snapshot of the in-process queue worker.

sync_status.py needs to answer "is a queued job actually going to be
picked up?", which depends on the worker's configuration and heartbeat.
It used to answer that by reading queue_worker's module-level mutable
global (`queue_worker.LAST_POLL_AT`) directly — a projection function
reaching into another module's private state, which both couples the two
modules at the field level and makes the projection untestable without
monkeypatching a global.

This value object is the seam: queue_worker produces one (it owns the
heartbeat), sync_status consumes one (it owns the vocabulary shown to
the user). Neither needs to know how the other stores anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WorkerHealth:
    """enabled: ENABLE_INPROCESS_WORKER is on for this process.
    last_poll_at: when the worker loop last started an iteration, or None
    if it has never polled (not started, or started but wedged before the
    first iteration)."""

    enabled: bool
    last_poll_at: datetime | None

    def heartbeat_is_stale(self, *, now: datetime, threshold_seconds: float) -> bool:
        """True when the worker has not polled recently enough to be
        trusted as running — including the never-polled case."""
        if self.last_poll_at is None:
            return True
        return (now - self.last_poll_at).total_seconds() > threshold_seconds
