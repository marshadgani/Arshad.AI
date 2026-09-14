"""Table-driven unit tests for sync_status.derive_job_view — pure, no DB.

Covers the FEAT-144 test matrix from the system design: terminal states,
the picked/pending stall thresholds, the three worker-liveness states
(True/False/None), the attempt>0 retry case, and naive-datetime input.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from src.services.ingestion.sync_status import derive_job_view

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


def _ago(seconds: int) -> datetime:
    return NOW - timedelta(seconds=seconds)


def test_completed_status_is_completed_progress():
    view = derive_job_view(
        job_id="j1",
        status="completed",
        requested_at=_ago(120),
        picked_at=_ago(100),
        completed_at=_ago(5),
        error_text=None,
        attempt=1,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "completed"
    assert view["stalled_reason"] is None


def test_failed_status_is_failed_progress_with_error_surfaced():
    view = derive_job_view(
        job_id="j2",
        status="failed",
        requested_at=_ago(300),
        picked_at=_ago(250),
        completed_at=_ago(10),
        error_text="HttpError: 401 invalid_grant",
        attempt=3,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "failed"
    assert view["error_text"] == "HttpError: 401 invalid_grant"


def test_pending_worker_disabled_is_immediately_stalled():
    view = derive_job_view(
        job_id="j3",
        status="pending",
        requested_at=_ago(1),
        picked_at=None,
        completed_at=None,
        error_text=None,
        attempt=0,
        worker_enabled=False,
        worker_alive=None,
        now=NOW,
    )
    assert view["progress"] == "stalled"
    assert view["stalled_reason"] == "no_worker_running"


def test_pending_worker_enabled_and_alive_is_processing():
    view = derive_job_view(
        job_id="j4",
        status="pending",
        requested_at=_ago(1),
        picked_at=None,
        completed_at=None,
        error_text=None,
        attempt=0,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "processing"


def test_pending_worker_not_alive_within_grace_is_processing():
    view = derive_job_view(
        job_id="j5",
        status="pending",
        requested_at=_ago(10),
        picked_at=None,
        completed_at=None,
        error_text=None,
        attempt=0,
        worker_enabled=True,
        worker_alive=False,
        now=NOW,
    )
    assert view["progress"] == "processing"


def test_pending_worker_not_alive_past_grace_is_stalled():
    view = derive_job_view(
        job_id="j6",
        status="pending",
        requested_at=_ago(120),
        picked_at=None,
        completed_at=None,
        error_text=None,
        attempt=0,
        worker_enabled=True,
        worker_alive=False,
        now=NOW,
    )
    assert view["progress"] == "stalled"
    assert view["stalled_reason"] == "worker_not_responding"


def test_pending_worker_liveness_unknown_never_manufactures_stalled():
    view = derive_job_view(
        job_id="j7",
        status="pending",
        requested_at=_ago(600),
        picked_at=None,
        completed_at=None,
        error_text=None,
        attempt=0,
        worker_enabled=True,
        worker_alive=None,
        now=NOW,
    )
    assert view["progress"] == "processing"


def test_pending_retry_with_prior_error_sets_retrying_flag():
    view = derive_job_view(
        job_id="j8",
        status="pending",
        requested_at=_ago(30),
        picked_at=None,
        completed_at=None,
        error_text="TimeoutError: upstream took too long",
        attempt=1,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "processing"
    assert view["retrying"] is True
    assert view["attempt"] == 1


def test_pending_second_retry_still_processing_and_retrying():
    view = derive_job_view(
        job_id="j9",
        status="pending",
        requested_at=_ago(30),
        picked_at=None,
        completed_at=None,
        error_text="TimeoutError",
        attempt=2,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "processing"
    assert view["retrying"] is True


def test_picked_within_threshold_is_processing():
    view = derive_job_view(
        job_id="j10",
        status="picked",
        requested_at=_ago(400),
        picked_at=_ago(300),
        completed_at=None,
        error_text=None,
        attempt=1,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "processing"


def test_picked_past_threshold_is_stalled_worker_timeout():
    view = derive_job_view(
        job_id="j11",
        status="picked",
        requested_at=_ago(1400),
        picked_at=_ago(1300),  # > 15 minutes
        completed_at=None,
        error_text=None,
        attempt=1,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "stalled"
    assert view["stalled_reason"] == "worker_timeout"


def test_naive_requested_at_does_not_raise():
    naive = datetime(2026, 9, 14, 11, 59, 0)  # no tzinfo — legacy row
    view = derive_job_view(
        job_id="j12",
        status="pending",
        requested_at=naive,
        picked_at=None,
        completed_at=None,
        error_text=None,
        attempt=0,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["progress"] == "processing"
    assert view["requested_at"] is not None


def test_airflow_drainer_treated_as_worker_enabled_with_unknown_liveness():
    """docker-compose dev: ENABLE_INPROCESS_WORKER=false, QUEUE_DRAINER=
    airflow — the caller passes worker_enabled=True (via
    queue.drainer.is_drained()) and worker_alive=None (no heartbeat exists
    for Airflow). Must not stall."""
    view = derive_job_view(
        job_id="j13",
        status="pending",
        requested_at=_ago(600),
        picked_at=None,
        completed_at=None,
        error_text=None,
        attempt=0,
        worker_enabled=True,
        worker_alive=None,
        now=NOW,
    )
    assert view["progress"] == "processing"


@pytest.mark.parametrize("status", ["pending", "picked", "completed", "failed"])
def test_job_id_and_status_always_echoed(status):
    view = derive_job_view(
        job_id="echo-me",
        status=status,
        requested_at=_ago(5),
        picked_at=_ago(3) if status in ("picked", "completed", "failed") else None,
        completed_at=_ago(1) if status in ("completed", "failed") else None,
        error_text="boom" if status == "failed" else None,
        attempt=0,
        worker_enabled=True,
        worker_alive=True,
        now=NOW,
    )
    assert view["job_id"] == "echo-me"
    assert view["status"] == status
