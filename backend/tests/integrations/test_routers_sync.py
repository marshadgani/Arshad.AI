"""Integration tests for POST /{slug}/sync and GET /{slug}/sync/status
against the FastAPI app (ASGI transport, no real DB).

All provider sync calls and dag_queue calls are patched at the service
layer; the HTTP layer is exercised against a real test client wired via
the conftest.py fixtures (async_client, auth_headers).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from .conftest import patch_provider_sync

# ── POST /{slug}/sync ──────────────────────────────────────────────────────


# TC-020 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_google_calendar_returns_queued_shape(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-020: POST /api/v1/integrations/google_calendar/sync on a connected
    integration returns {mode: 'queued', job_id: <uuid>, status: 'pending', summary}."""
    from src.integrations.base import EnqueuedResult
    from src.models.integration import Integration

    mock_job_id = str(uuid.uuid4())
    mock_result = EnqueuedResult(
        job_id=mock_job_id,
        dag_id="calendar_ingestor",
        summary="Queued calendar_ingestor for processing.",
    )
    mock_integration = MagicMock(spec=Integration)
    mock_integration.user_id = uuid.uuid4()
    mock_integration.slug = "google_calendar"

    with (
        patch(
            "src.integrations.routers._find_user_integration",
            new=AsyncMock(return_value=mock_integration),
        ),
        patch_provider_sync("google_calendar", mock_result) as sync_stub,
    ):
        resp = await async_client.post(
            "/api/v1/integrations/google_calendar/sync", headers=auth_headers
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["mode"] == "queued"
    assert "job_id" in body
    assert body["status"] == "pending"
    assert "summary" in body
    assert "rows_written" not in body
    sync_stub.assert_awaited_once()


# TC-021 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_gmail_returns_queued_shape(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-021: POST /api/v1/integrations/gmail/sync returns mode='queued'."""
    from src.integrations.base import EnqueuedResult
    from src.models.integration import Integration

    mock_result = EnqueuedResult(
        job_id=str(uuid.uuid4()),
        dag_id="email_ingestor",
        summary="Queued email_ingestor for processing.",
    )
    mock_integration = MagicMock(spec=Integration)
    mock_integration.user_id = uuid.uuid4()
    mock_integration.slug = "gmail"

    with (
        patch(
            "src.integrations.routers._find_user_integration",
            new=AsyncMock(return_value=mock_integration),
        ),
        patch_provider_sync("gmail", mock_result) as sync_stub,
    ):
        resp = await async_client.post(
            "/api/v1/integrations/gmail/sync", headers=auth_headers
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["mode"] == "queued"
    sync_stub.assert_awaited_once()


# TC-022 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_github_returns_queued_shape(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-022: POST /api/v1/integrations/github/sync returns mode='queued'."""
    from src.integrations.base import EnqueuedResult
    from src.models.integration import Integration

    mock_result = EnqueuedResult(
        job_id=str(uuid.uuid4()),
        dag_id="github_ingestor",
        summary="Queued github_ingestor for processing.",
    )
    mock_integration = MagicMock(spec=Integration)
    mock_integration.user_id = uuid.uuid4()
    mock_integration.slug = "github"

    with (
        patch(
            "src.integrations.routers._find_user_integration",
            new=AsyncMock(return_value=mock_integration),
        ),
        patch_provider_sync("github", mock_result) as sync_stub,
    ):
        resp = await async_client.post(
            "/api/v1/integrations/github/sync", headers=auth_headers
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["mode"] == "queued"
    sync_stub.assert_awaited_once()


# TC-023 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_unknown_slug_returns_404(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-023: POST /api/v1/integrations/does_not_exist/sync → 404 with
    error.code='unknown_integration'."""
    resp = await async_client.post(
        "/api/v1/integrations/does_not_exist/sync", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_integration"


# TC-024 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_unauthenticated_returns_401(async_client: AsyncClient):
    """TC-024: POST /api/v1/integrations/google_calendar/sync without auth → 401."""
    from httpx import ASGITransport
    from httpx import AsyncClient as _AsyncClient
    from src.main import app

    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        transport = ASGITransport(app=app)
        async with _AsyncClient(
            transport=transport, base_url="http://test"
        ) as bare_client:
            resp = await bare_client.post("/api/v1/integrations/google_calendar/sync")
    finally:
        app.dependency_overrides.update(saved_overrides)

    assert resp.status_code == 401


# TC-025 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_not_connected_returns_400(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-025: POST sync for a slug the user has no Integration row for → 400
    with error.code='not_connected'."""
    with patch(
        "src.integrations.routers._find_user_integration",
        new=AsyncMock(return_value=None),
    ):
        resp = await async_client.post(
            "/api/v1/integrations/google_calendar/sync", headers=auth_headers
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_connected"


# ── GET /{slug}/sync/status ───────────────────────────────────────────────


# TC-030 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_synchronous_provider_returns_404(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-030: GET /api/v1/integrations/shopify/sync/status → 404
    error.code='unknown_sync_job' (shopify has sync_dag_id=None)."""
    resp = await async_client.get(
        "/api/v1/integrations/shopify/sync/status", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_sync_job"


# TC-031 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_no_row_returns_null(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-031: GET .../google_calendar/sync/status when no DagTriggerQueue row
    exists for this user → {data: null}."""
    with patch("src.services.dag_queue.latest_job", new=AsyncMock(return_value=None)):
        resp = await async_client.get(
            "/api/v1/integrations/google_calendar/sync/status", headers=auth_headers
        )
    assert resp.status_code == 200
    assert resp.json()["data"] is None


# TC-032 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_pending_row_returns_pending(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-032: pending row, age < 60s → status='pending' in response."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.dag_id = "calendar_ingestor"
    row.status = "pending"
    row.requested_at = datetime.now(timezone.utc)
    row.picked_at = None
    row.completed_at = None
    row.attempt = 0
    row.error_text = None

    with patch("src.services.dag_queue.latest_job", new=AsyncMock(return_value=row)):
        resp = await async_client.get(
            "/api/v1/integrations/google_calendar/sync/status", headers=auth_headers
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "pending"
    assert data["job_id"] == str(row.id)


# TC-033 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_stalled_row_returns_stalled(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-033: pending row, age > 60s, worker disabled → status='stalled',
    message contains ENABLE_INPROCESS_WORKER."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.dag_id = "calendar_ingestor"
    row.status = "pending"
    row.requested_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    row.picked_at = None
    row.completed_at = None
    row.attempt = 0
    row.error_text = None

    with (
        patch("src.services.dag_queue.latest_job", new=AsyncMock(return_value=row)),
        patch("src.services.queue_worker.is_enabled", return_value=False),
        patch(
            "src.services.queue_worker.health",
            return_value=__import__(
                "src.services.worker_health", fromlist=["WorkerHealth"]
            ).WorkerHealth(enabled=False, last_poll_at=None),
        ),
    ):
        resp = await async_client.get(
            "/api/v1/integrations/google_calendar/sync/status", headers=auth_headers
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "stalled"
    assert "ENABLE_INPROCESS_WORKER" in (data["message"] or "")


# TC-034 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_idor_user_b_cannot_see_user_a_job(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-034: IDOR — user B passes user A's job_id as query param;
    dag_queue.latest_job filters by current user_id, so user B gets null."""
    user_a_job_id = str(uuid.uuid4())
    with patch("src.services.dag_queue.latest_job", new=AsyncMock(return_value=None)):
        resp = await async_client.get(
            f"/api/v1/integrations/google_calendar/sync/status?job_id={user_a_job_id}",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["data"] is None


# TC-035 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_invalid_job_id_uuid_returns_422(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-035: job_id query param that is not a valid UUID → 422
    error.code='invalid_job_id'."""
    resp = await async_client.get(
        "/api/v1/integrations/google_calendar/sync/status?job_id=not-a-uuid",
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_job_id"


# TC-036 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_completed_row(async_client: AsyncClient, auth_headers: dict):
    """TC-036: completed row → completed_at populated, status='completed'."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.dag_id = "calendar_ingestor"
    row.status = "completed"
    row.requested_at = datetime.now(timezone.utc)
    row.picked_at = datetime.now(timezone.utc)
    row.completed_at = datetime.now(timezone.utc)
    row.attempt = 1
    row.error_text = None

    with patch("src.services.dag_queue.latest_job", new=AsyncMock(return_value=row)):
        resp = await async_client.get(
            "/api/v1/integrations/google_calendar/sync/status", headers=auth_headers
        )

    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["completed_at"] is not None


# TC-037 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_failed_row_error_populated(
    async_client: AsyncClient, auth_headers: dict
):
    """TC-037: failed row → error field populated from error_text."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.dag_id = "email_ingestor"
    row.status = "failed"
    row.requested_at = datetime.now(timezone.utc)
    row.picked_at = datetime.now(timezone.utc)
    row.completed_at = None
    row.attempt = 3
    row.error_text = "TokenExpiredError: access token expired"

    with patch("src.services.dag_queue.latest_job", new=AsyncMock(return_value=row)):
        resp = await async_client.get(
            "/api/v1/integrations/gmail/sync/status", headers=auth_headers
        )

    data = resp.json()["data"]
    assert data["status"] == "failed"
    assert "TokenExpiredError" in data["error"]


# TC-038 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_status_unauthenticated_returns_401(async_client: AsyncClient):
    """TC-038: GET sync/status without auth → 401."""
    from httpx import ASGITransport
    from httpx import AsyncClient as _AsyncClient
    from src.main import app

    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        transport = ASGITransport(app=app)
        async with _AsyncClient(
            transport=transport, base_url="http://test"
        ) as bare_client:
            resp = await bare_client.get(
                "/api/v1/integrations/google_calendar/sync/status"
            )
    finally:
        app.dependency_overrides.update(saved_overrides)

    assert resp.status_code == 401
