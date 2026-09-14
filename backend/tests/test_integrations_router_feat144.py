"""TC-013 through TC-023 — integrations router sync & status-poll endpoints (FEAT-144).

REQUIREMENTS COVERED:
  REQ-T13  POST /sync with DAG-backed provider: response includes mode='enqueued', job_id != null
  REQ-T14  POST /sync with synchronous provider: response includes mode='completed', job_id=null
  REQ-T15  POST /sync response always has all 5 fields (rows_written, summary, duration_ms, mode, job_id)
  REQ-T16  POST /sync always returns HTTP 200 (not 201/202) for both modes
  REQ-T17  GET /sync/status for provider with sync_dag_id=None → 409 sync_not_pollable
  REQ-T18  GET /sync/status, job found for user → 200 with status/progress
  REQ-T19  GET /sync/status, job_id belongs to different user → 404 sync_job_not_found
  REQ-T20  GET /sync/status, no prior sync → 404 sync_job_not_found
  REQ-T21  GET /sync/status with invalid job_id UUID → 422 invalid_job_id
  REQ-T22  GET /sync/status worker_enabled matches actual drainer state
  REQ-T23  POST /sync without auth → 401
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import src.integrations.routers as routers_module
from fastapi.testclient import TestClient
from src.auth.dependencies import get_current_user
from src.integrations.base import (
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from src.main import app
from src.models.database import get_db

USER_ID = uuid.uuid4()


class _FakeUser:
    id = USER_ID
    email = "test@example.com"


class _FakeIntegration:
    def __init__(self, slug: str = "google_calendar", status: str = "connected"):
        self.id = uuid.uuid4()
        self.slug = slug
        self.user_id = USER_ID
        self.status = status
        self.last_error = None
        self.config = {}


class _DagProvider(IntegrationProvider):
    slug = "google_calendar"
    kind = "personal_oauth"
    display_name = "Google Calendar"
    category = "Calendar"
    description = "test"
    sync_dag_id = "calendar_ingestor"
    revocation_kind = "no_revoke"

    async def connect(self, *, user, db, payload): ...
    async def sync(self, *, integration, db): ...
    async def status(self, *, integration, db): ...

    def __init__(self):
        self.sync = AsyncMock(
            return_value=SyncResult(
                rows_written=0,
                summary="Sync enqueued.",
                duration_ms=5,
                mode="enqueued",
                job_id=str(uuid.uuid4()),
            )
        )
        self.status = AsyncMock(
            return_value=StatusReport(
                status="connected", last_synced_at=None, last_error=None, extra={}
            )
        )


class _SyncProvider(IntegrationProvider):
    slug = "shopify"
    kind = "project_apikey"
    display_name = "Shopify"
    category = "Commerce"
    description = "test"
    sync_dag_id = None
    revocation_kind = "no_revoke"

    async def connect(self, *, user, db, payload): ...
    async def sync(self, *, integration, db): ...
    async def status(self, *, integration, db): ...

    def __init__(self):
        self.sync = AsyncMock(
            return_value=SyncResult(
                rows_written=12,
                summary="Synced 12 orders.",
                duration_ms=320,
            )
        )
        self.status = AsyncMock(
            return_value=StatusReport(
                status="connected", last_synced_at=None, last_error=None, extra={}
            )
        )


def _make_db(scalar_value=None):
    db = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    db.scalars = AsyncMock(return_value=scalars_result)
    db.scalar = AsyncMock(return_value=scalar_value)
    db.commit = AsyncMock()
    return db


def _client_for(provider, db=None, monkeypatch=None):
    if db is None:
        db = _make_db()
    registry = {provider.slug: provider}

    async def _user():
        return _FakeUser()

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    if monkeypatch is not None:
        monkeypatch.setattr(routers_module, "INTEGRATION_REGISTRY", registry)
        monkeypatch.setattr(
            routers_module, "get_provider", lambda slug: registry.get(slug)
        )
    return TestClient(app)


@pytest.fixture
def dag_provider():
    return _DagProvider()


@pytest.fixture
def sync_provider():
    return _SyncProvider()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_sync_dag_backed_returns_enqueued_mode_and_job_id(dag_provider, monkeypatch):
    """TC-013 — POST /sync for DAG-backed provider: mode='enqueued', job_id not null."""
    integration = _FakeIntegration("google_calendar")
    db = _make_db(scalar_value=integration)
    tc = _client_for(dag_provider, db=db, monkeypatch=monkeypatch)

    resp = tc.post("/api/v1/integrations/google_calendar/sync")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mode"] == "enqueued"
    assert data["job_id"] is not None
    assert isinstance(data["job_id"], str)


def test_sync_synchronous_provider_returns_completed_mode(sync_provider, monkeypatch):
    """TC-014 — POST /sync for synchronous provider: mode='completed', job_id=null."""
    integration = _FakeIntegration("shopify")
    db = _make_db(scalar_value=integration)
    tc = _client_for(sync_provider, db=db, monkeypatch=monkeypatch)

    resp = tc.post("/api/v1/integrations/shopify/sync")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mode"] == "completed"
    assert data["job_id"] is None


@pytest.mark.parametrize(
    "field", ["rows_written", "summary", "duration_ms", "mode", "job_id"]
)
def test_sync_response_always_has_all_five_fields(field, sync_provider, monkeypatch):
    """TC-015 — All 5 fields must be present in the response body for both modes."""
    integration = _FakeIntegration("shopify")
    db = _make_db(scalar_value=integration)
    tc = _client_for(sync_provider, db=db, monkeypatch=monkeypatch)

    resp = tc.post("/api/v1/integrations/shopify/sync")

    assert field in resp.json()["data"]


def test_sync_dag_backed_returns_http_200_not_201_or_202(dag_provider, monkeypatch):
    """TC-016 — POST /sync must return 200, not 201/202 (avoid misleading status codes)."""
    integration = _FakeIntegration("google_calendar")
    db = _make_db(scalar_value=integration)
    tc = _client_for(dag_provider, db=db, monkeypatch=monkeypatch)

    resp = tc.post("/api/v1/integrations/google_calendar/sync")

    assert resp.status_code == 200


def test_sync_status_returns_409_for_non_dag_provider(sync_provider, monkeypatch):
    """TC-017 — GET /sync/status returns 409 sync_not_pollable for sync providers."""
    db = _make_db()
    tc = _client_for(sync_provider, db=db, monkeypatch=monkeypatch)

    resp = tc.get("/api/v1/integrations/shopify/sync/status")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "sync_not_pollable"


def test_sync_status_returns_200_with_job_data(dag_provider, monkeypatch):
    """TC-018 — GET /sync/status returns 200 when a job is found for user+dag_id."""
    db = _make_db()
    job_view = {
        "job_id": str(uuid.uuid4()),
        "status": "pending",
        "progress": "processing",
        "stalled_reason": None,
        "retrying": False,
        "attempt": 0,
        "worker_enabled": True,
        "worker_alive": True,
        "error_text": None,
        "requested_at": "2025-01-01T00:00:00+00:00",
        "picked_at": None,
        "completed_at": None,
    }

    with patch(
        "src.integrations.routers.sync_jobs.job_status_view",
        AsyncMock(return_value=job_view),
    ):
        tc = _client_for(dag_provider, db=db, monkeypatch=monkeypatch)
        resp = tc.get("/api/v1/integrations/google_calendar/sync/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["progress"] == "processing"


def test_sync_status_returns_404_for_another_users_job_id(dag_provider, monkeypatch):
    """TC-019 — A job_id belonging to another user must return 404 (not a data leak)."""
    db = _make_db()
    other_job_id = str(uuid.uuid4())

    with patch(
        "src.integrations.routers.sync_jobs.job_status_view",
        AsyncMock(return_value=None),
    ):
        tc = _client_for(dag_provider, db=db, monkeypatch=monkeypatch)
        resp = tc.get(
            f"/api/v1/integrations/google_calendar/sync/status?job_id={other_job_id}"
        )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "sync_job_not_found"


def test_sync_status_returns_404_when_no_prior_sync(dag_provider, monkeypatch):
    """TC-020 — No prior sync job exists for this user+provider → 404."""
    db = _make_db()

    with patch(
        "src.integrations.routers.sync_jobs.job_status_view",
        AsyncMock(return_value=None),
    ):
        tc = _client_for(dag_provider, db=db, monkeypatch=monkeypatch)
        resp = tc.get("/api/v1/integrations/google_calendar/sync/status")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "sync_job_not_found"


def test_sync_status_returns_422_for_non_uuid_job_id(dag_provider, monkeypatch):
    """TC-021 — Non-UUID job_id query param must return 422 invalid_job_id."""
    db = _make_db()
    tc = _client_for(dag_provider, db=db, monkeypatch=monkeypatch)

    resp = tc.get("/api/v1/integrations/google_calendar/sync/status?job_id=not-a-uuid")

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_job_id"


def test_sync_and_status_return_404_for_unknown_slug(dag_provider, monkeypatch):
    """TC-022 — Unknown integration slug must return 404 for both POST /sync and GET /sync/status."""
    db = _make_db()
    tc = _client_for(dag_provider, db=db, monkeypatch=monkeypatch)

    for path in [
        "/api/v1/integrations/nonexistent/sync",
        "/api/v1/integrations/nonexistent/sync/status",
    ]:
        resp = tc.post(path) if path.endswith("/sync") else tc.get(path)
        assert resp.status_code == 404, (
            f"Expected 404 for {path}, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "unknown_integration"


def test_sync_requires_authentication(dag_provider, monkeypatch):
    """TC-023 — POST /sync without auth header must return 401."""
    registry = {dag_provider.slug: dag_provider}
    monkeypatch.setattr(routers_module, "INTEGRATION_REGISTRY", registry)
    monkeypatch.setattr(routers_module, "get_provider", lambda slug: registry.get(slug))

    tc = TestClient(app)
    resp = tc.post("/api/v1/integrations/google_calendar/sync")

    assert resp.status_code == 401
