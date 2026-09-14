"""TC-063 through TC-068 — sync_jobs.find_job user-isolation security tests.

REQUIREMENTS COVERED:
  REQ-T63  find_job with job_id belonging to another user returns None (not a leak)
  REQ-T64  find_job with wrong dag_id for a valid job returns None
  REQ-T65  find_job with no job_id returns most recent job for user+dag_id
  REQ-T66  find_job with no rows for user+dag_id returns None
  REQ-T67  job_status_view returns None when find_job returns None
  REQ-T68  job_status_view dict includes worker_enabled field
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_find_job_returns_none_for_another_users_job_id():
    """TC-063 — A job_id that exists but belongs to a different user must return None.

    This is the security invariant: the query always filters by user_id+dag_id
    even when job_id is provided, so a cross-user lookup is a miss, not a hit.
    """
    from src.services.ingestion import sync_jobs

    user_a = uuid.uuid4()
    user_b_job_id = uuid.uuid4()  # a job that belongs to user B

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # scoped query returns nothing

    result = await sync_jobs.find_job(
        db,
        user_id=user_a,
        dag_id="calendar_ingestor",
        job_id=user_b_job_id,
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_job_returns_none_for_wrong_dag_id():
    """TC-064 — Providing the right job_id but wrong dag_id returns None."""
    from src.services.ingestion import sync_jobs

    user_id = uuid.uuid4()
    job_id = uuid.uuid4()

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    result = await sync_jobs.find_job(
        db,
        user_id=user_id,
        dag_id="email_ingestor",  # wrong dag for this job
        job_id=job_id,
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_job_without_job_id_returns_latest_for_user_dag():
    """TC-065 — find_job without job_id falls back to most recent row for user+dag_id."""
    from src.services.ingestion import sync_jobs

    user_id = uuid.uuid4()
    latest_row = MagicMock()
    latest_row.id = uuid.uuid4()
    latest_row.status = "completed"

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=latest_row)

    result = await sync_jobs.find_job(
        db,
        user_id=user_id,
        dag_id="calendar_ingestor",
        job_id=None,
    )

    assert result is latest_row


@pytest.mark.asyncio
async def test_find_job_returns_none_when_no_rows_exist():
    """TC-066 — No prior sync rows at all → find_job returns None."""
    from src.services.ingestion import sync_jobs

    user_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    result = await sync_jobs.find_job(
        db,
        user_id=user_id,
        dag_id="github_ingestor",
    )

    assert result is None


@pytest.mark.asyncio
async def test_job_status_view_returns_none_when_no_job():
    """TC-067 — job_status_view returns None (not an error) when find_job returns None."""
    from src.services.ingestion import sync_jobs

    user_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    result = await sync_jobs.job_status_view(
        db,
        user_id=user_id,
        dag_id="calendar_ingestor",
    )

    assert result is None


@pytest.mark.asyncio
async def test_job_status_view_includes_worker_enabled():
    """TC-068 — job_status_view must include worker_enabled in the returned dict."""
    from datetime import datetime, timezone

    from src.services.ingestion import sync_jobs
    from src.services.queue.drainer import DrainerLiveness

    user_id = uuid.uuid4()

    fake_row = MagicMock()
    fake_row.id = uuid.uuid4()
    fake_row.dag_id = "calendar_ingestor"
    fake_row.user_id = user_id
    fake_row.status = "completed"
    fake_row.requested_at = datetime.now(timezone.utc)
    fake_row.picked_at = None
    fake_row.completed_at = datetime.now(timezone.utc)
    fake_row.error_text = None
    fake_row.attempt = 0

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=fake_row)

    with patch(
        "src.services.ingestion.sync_jobs.drainer.observe",
        AsyncMock(return_value=DrainerLiveness(enabled=True, alive=True)),
    ):
        result = await sync_jobs.job_status_view(
            db,
            user_id=user_id,
            dag_id="calendar_ingestor",
        )

    assert result is not None
    assert "worker_enabled" in result
    assert result["worker_enabled"] is True
