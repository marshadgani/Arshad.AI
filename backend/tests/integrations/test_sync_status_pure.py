"""TC-024 through TC-036 — derive_job_view pure state-machine tests.

REQUIREMENTS COVERED:
  REQ-T24  status='completed' → progress='completed'
  REQ-T25  status='failed'    → progress='failed', error_text surfaced
  REQ-T26  status='pending', worker_enabled=True → progress='processing'
  REQ-T27  status='picked',  picked_at < 15min ago → progress='processing'
  REQ-T28  status='pending', worker_enabled=False → progress='stalled', reason='no_worker_running'
  REQ-T29  status='pending', worker_alive=False, age>60s → progress='stalled', reason='worker_not_responding'
  REQ-T30  status='pending', worker_alive=False, age<60s → progress='processing' (grace period)
  REQ-T31  status='picked',  picked_at > 15min ago → progress='stalled', reason='worker_timeout'
  REQ-T32  worker_alive=None (unknown) must never produce stalled verdict
  REQ-T33  retrying=True when pending, attempt>0, error_text set
  REQ-T34  unrecognised status falls back to progress='processing' without raising
  REQ-T35  naive datetimes treated as UTC (no TypeError)
  REQ-T36  all output fields always present
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from src.services.ingestion.sync_status import derive_job_view


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _view(
    status: str = "pending",
    *,
    requested_at: datetime | None = None,
    picked_at: datetime | None = None,
    completed_at: datetime | None = None,
    error_text: str | None = None,
    attempt: int = 0,
    worker_enabled: bool = True,
    worker_alive: bool | None = True,
    now: datetime | None = None,
) -> dict:
    return derive_job_view(
        job_id="test-job",
        status=status,
        requested_at=requested_at or _now(),
        picked_at=picked_at,
        completed_at=completed_at,
        error_text=error_text,
        attempt=attempt,
        worker_enabled=worker_enabled,
        worker_alive=worker_alive,
        now=now,
    )


def test_completed_status_yields_completed_progress():
    """TC-024 — status='completed' → progress='completed'."""
    v = _view(status="completed", completed_at=_now())
    assert v["progress"] == "completed"
    assert v["stalled_reason"] is None


def test_failed_status_yields_failed_progress_with_error():
    """TC-025 — status='failed' → progress='failed', error_text passed through."""
    v = _view(status="failed", error_text="boom")
    assert v["progress"] == "failed"
    assert v["error_text"] == "boom"


def test_pending_with_healthy_worker_is_processing():
    """TC-026 — status='pending', worker enabled and alive → progress='processing'."""
    v = _view(status="pending", worker_enabled=True, worker_alive=True)
    assert v["progress"] == "processing"
    assert v["stalled_reason"] is None


def test_picked_recently_is_processing():
    """TC-027 — status='picked', picked_at=1min ago → progress='processing'."""
    picked = _now() - timedelta(minutes=1)
    v = _view(status="picked", picked_at=picked)
    assert v["progress"] == "processing"


def test_pending_no_worker_enabled_is_stalled_immediately():
    """TC-028 — status='pending', worker_enabled=False → stalled immediately (no grace)."""
    v = _view(status="pending", worker_enabled=False, worker_alive=None)
    assert v["progress"] == "stalled"
    assert v["stalled_reason"] == "no_worker_running"


def test_pending_dead_worker_over_grace_period_is_stalled():
    """TC-029 — Pending row older than the grace period with worker_alive=False → stalled."""
    from src.services.ingestion.sync_status import PENDING_NO_HEARTBEAT_GRACE

    old_requested = _now() - PENDING_NO_HEARTBEAT_GRACE - timedelta(seconds=1)
    v = _view(
        status="pending",
        requested_at=old_requested,
        worker_enabled=True,
        worker_alive=False,
    )
    assert v["progress"] == "stalled"
    assert v["stalled_reason"] == "worker_not_responding"


def test_pending_dead_worker_within_grace_period_is_processing():
    """TC-030 — Pending row younger than the grace period with worker_alive=False: still processing."""
    fresh_requested = _now() - timedelta(seconds=10)
    v = _view(
        status="pending",
        requested_at=fresh_requested,
        worker_enabled=True,
        worker_alive=False,
    )
    assert v["progress"] == "processing"


def test_picked_over_stall_threshold_is_stalled():
    """TC-031 — status='picked', picked_at past the stall threshold → stalled with reason='worker_timeout'."""
    from src.services.ingestion.sync_status import PICKED_STALL_AFTER

    old_picked = _now() - PICKED_STALL_AFTER - timedelta(seconds=1)
    v = _view(status="picked", picked_at=old_picked)
    assert v["progress"] == "stalled"
    assert v["stalled_reason"] == "worker_timeout"


def test_unknown_liveness_never_causes_stalled():
    """TC-032 — worker_alive=None (unknown) must not produce a stalled verdict."""
    from src.services.ingestion.sync_status import PENDING_NO_HEARTBEAT_GRACE

    old_requested = _now() - PENDING_NO_HEARTBEAT_GRACE - timedelta(seconds=1)
    v = _view(
        status="pending",
        requested_at=old_requested,
        worker_enabled=True,
        worker_alive=None,  # unknown — e.g. Redis unreachable
    )
    assert v["progress"] != "stalled"


def test_retrying_true_when_attempt_gt_0_and_error_set():
    """TC-033 — retrying=True when attempt>0 AND error_text is set."""
    v = _view(status="pending", attempt=1, error_text="transient error")
    assert v["retrying"] is True


def test_retrying_false_when_no_prior_error():
    """TC-033b — retrying=False when error_text is None (first attempt)."""
    v = _view(status="pending", attempt=0, error_text=None)
    assert v["retrying"] is False


def test_unrecognised_status_falls_back_to_processing_no_raise():
    """TC-034 — An unrecognised status must not raise; falls back to progress='processing'."""
    v = _view(status="mystery_state")
    assert v["progress"] == "processing"  # graceful fallback


def test_naive_datetime_treated_as_utc():
    """TC-035 — Naive datetime in requested_at must not raise TypeError."""
    naive_now = datetime.utcnow()  # naive, no tzinfo
    try:
        v = derive_job_view(
            job_id="x",
            status="pending",
            requested_at=naive_now,
            picked_at=None,
            completed_at=None,
            error_text=None,
            attempt=0,
            worker_enabled=True,
            worker_alive=True,
        )
    except TypeError as exc:
        pytest.fail(f"Naive datetime raised TypeError: {exc}")
    assert v["progress"] in {"processing", "stalled", "completed", "failed"}


@pytest.mark.parametrize(
    "key",
    [
        "job_id",
        "status",
        "progress",
        "stalled_reason",
        "retrying",
        "attempt",
        "worker_enabled",
        "worker_alive",
        "error_text",
        "requested_at",
        "picked_at",
        "completed_at",
    ],
)
def test_all_output_fields_always_present(key):
    """TC-036 — All fields must be present in every derive_job_view output."""
    v = _view()
    assert key in v, f"Missing field: {key}"
