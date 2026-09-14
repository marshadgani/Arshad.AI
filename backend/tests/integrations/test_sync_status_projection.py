"""Unit tests for services/sync_status.py — project_job() is a pure
function; no DB or worker process required.

All 'now' and WorkerHealth values are injected to keep tests deterministic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.services.sync_status import (
    STALE_THRESHOLD_SECONDS,
    project_job,
)
from src.services.worker_health import WorkerHealth


def _make_row(
    *,
    status: str = "pending",
    requested_at: datetime | None = None,
    picked_at: datetime | None = None,
    completed_at: datetime | None = None,
    attempt: int = 0,
    error_text: str | None = None,
) -> MagicMock:
    now = datetime.now(timezone.utc)
    row = MagicMock()
    row.id = uuid.uuid4()
    row.dag_id = "calendar_ingestor"
    row.status = status
    row.requested_at = requested_at or now
    row.picked_at = picked_at
    row.completed_at = completed_at
    row.attempt = attempt
    row.error_text = error_text
    return row


def _worker(enabled: bool, last_poll_at: datetime | None = None) -> WorkerHealth:
    return WorkerHealth(enabled=enabled, last_poll_at=last_poll_at)


# TC-010 ───────────────────────────────────────────────────────────────────────────
def test_project_job_pending_young_no_stall():
    """TC-010: pending row, age < STALE_THRESHOLD_SECONDS → status='pending',
    message=None."""
    now = datetime.now(timezone.utc)
    row = _make_row(status="pending", requested_at=now - timedelta(seconds=10))
    health = _worker(enabled=True, last_poll_at=now)
    result = project_job(row, now=now, health=health)
    assert result["status"] == "pending"
    assert result["message"] is None


# TC-011 ───────────────────────────────────────────────────────────────────────────
def test_project_job_pending_stale_worker_disabled():
    """TC-011: pending row, age > STALE_THRESHOLD_SECONDS, worker disabled
    → status='stalled', message contains ENABLE_INPROCESS_WORKER."""
    now = datetime.now(timezone.utc)
    age = timedelta(seconds=STALE_THRESHOLD_SECONDS + 1)
    row = _make_row(status="pending", requested_at=now - age)
    health = _worker(enabled=False)
    result = project_job(row, now=now, health=health)
    assert result["status"] == "stalled"
    assert "ENABLE_INPROCESS_WORKER" in result["message"]


# TC-012 ───────────────────────────────────────────────────────────────────────────
def test_project_job_pending_stale_heartbeat_dead():
    """TC-012: pending row, age > threshold, worker enabled but heartbeat stale
    → status='stalled', message references polling issue."""
    now = datetime.now(timezone.utc)
    age = timedelta(seconds=STALE_THRESHOLD_SECONDS + 1)
    stale_heartbeat = now - timedelta(seconds=120)
    row = _make_row(status="pending", requested_at=now - age)
    health = _worker(enabled=True, last_poll_at=stale_heartbeat)
    result = project_job(row, now=now, health=health)
    assert result["status"] == "stalled"
    assert result["message"] is not None


# TC-013 ───────────────────────────────────────────────────────────────────────────
def test_project_job_pending_stale_boundary_exactly_at_threshold():
    """TC-013: age exactly equal to STALE_THRESHOLD_SECONDS — verify
    inclusive/exclusive edge does not stall a row that's right on the threshold."""
    now = datetime.now(timezone.utc)
    row = _make_row(
        status="pending", requested_at=now - timedelta(seconds=STALE_THRESHOLD_SECONDS)
    )
    health = _worker(enabled=False)
    result = project_job(row, now=now, health=health)
    assert result["status"] == "pending"


# TC-014 ───────────────────────────────────────────────────────────────────────────
def test_project_job_picked_status_passes_through():
    """TC-014: row status='picked' → returned as-is, no stall logic applied."""
    now = datetime.now(timezone.utc)
    row = _make_row(status="picked", picked_at=now)
    health = _worker(enabled=True, last_poll_at=now)
    result = project_job(row, now=now, health=health)
    assert result["status"] == "picked"
    assert result["message"] is None


# TC-015 ───────────────────────────────────────────────────────────────────────────
def test_project_job_completed_fields():
    """TC-015: completed row → completed_at populated, error=None."""
    now = datetime.now(timezone.utc)
    row = _make_row(status="completed", completed_at=now)
    result = project_job(row, now=now, health=_worker(enabled=True, last_poll_at=now))
    assert result["status"] == "completed"
    assert result["completed_at"] is not None
    assert result["error"] is None


# TC-016 ───────────────────────────────────────────────────────────────────────────
def test_project_job_failed_error_field():
    """TC-016: failed row → error field populated from error_text."""
    now = datetime.now(timezone.utc)
    row = _make_row(status="failed", error_text="OAuthError: token expired")
    result = project_job(row, now=now, health=_worker(enabled=True, last_poll_at=now))
    assert result["status"] == "failed"
    assert "OAuthError" in result["error"]


# TC-017 ───────────────────────────────────────────────────────────────────────────
def test_project_job_pending_attempt_gt_zero_retrying():
    """TC-017: pending row with attempt > 0 → status retains 'pending'
    (retrying is a frontend-derived concept; the backend emits the raw
    status + attempt; the frontend decides the label)."""
    now = datetime.now(timezone.utc)
    row = _make_row(
        status="pending", attempt=2, requested_at=now - timedelta(seconds=5)
    )
    health = _worker(enabled=True, last_poll_at=now)
    result = project_job(row, now=now, health=health)
    assert result["attempt"] == 2
    assert result["status"] == "pending"


# TC-018 ───────────────────────────────────────────────────────────────────────────
def test_project_job_wire_shape_keys():
    """TC-018: returned dict always contains the required wire-shape keys."""
    row = _make_row()
    result = project_job(
        row,
        now=datetime.now(timezone.utc),
        health=_worker(enabled=True, last_poll_at=datetime.now(timezone.utc)),
    )
    for key in (
        "job_id",
        "dag_id",
        "status",
        "requested_at",
        "picked_at",
        "completed_at",
        "attempt",
        "error",
        "message",
    ):
        assert key in result, f"Missing wire-shape key: {key}"
