"""Tests for GET/POST /api/v1/integrations/* endpoints.

Covers:
- list: disconnected state, connected state, and provider.status() exception
  isolation (one bad provider must not blank the whole list)
- connect: happy path, unknown slug → 404, IntegrationError → 400
- disconnect: already disconnected, happy path
- status: unknown slug → 404, no integration row → disconnected, connected report

DB and auth are stubbed via FastAPI dependency overrides (same approach as
test_whoop_endpoints.py). INTEGRATION_REGISTRY and get_provider are
monkeypatched directly on the router module so the real providers (which
need live DB / HTTP) are never invoked.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import src.integrations.routers as routers_module
from src.auth.dependencies import get_current_user
from src.integrations.base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from src.main import app
from src.models.database import get_db

USER_ID = uuid.uuid4()


# ── test doubles ──────────────────────────────────────────────────────────


class _FakeUser:
    id = USER_ID


class _FakeIntegration:
    def __init__(self, slug: str = "test-provider", status: str = "connected"):
        self.id = uuid.uuid4()
        self.slug = slug
        self.user_id = USER_ID
        self.status = status
        self.last_error = None
        self.config = {}


class _FakeProvider(IntegrationProvider):
    """Minimal concrete provider whose async methods are injectable mocks.

    ABC requires class-level definitions for abstract methods; we satisfy
    that with no-op stubs then replace them with AsyncMocks per-instance
    so each test gets an independently controllable double.
    """

    slug = "test-provider"
    kind = "project_apikey"
    display_name = "Test Provider"
    category = "test"
    description = "A provider for tests."
    docs_url = None
    icon = "test"
    coming_soon = False
    coming_soon_reason = None
    connect_prompt = None

    # Class-level stubs satisfy ABC — overridden in __init__ with AsyncMocks
    async def connect(self, *, user, db, payload): ...  # type: ignore[override]
    async def sync(self, *, integration, db): ...  # type: ignore[override]
    async def status(self, *, integration, db): ...  # type: ignore[override]

    def __init__(self):
        self.connect = AsyncMock(
            return_value=ConnectResult(integration_id="int-1", redirect_url=None)
        )
        self.sync = AsyncMock(
            return_value=SyncResult(rows_written=0, summary="ok", duration_ms=10)
        )
        self.status = AsyncMock(
            return_value=StatusReport(
                status="connected",
                last_synced_at="2024-01-01T00:00:00Z",
                last_error=None,
                extra={},
            )
        )
        self.disconnect = AsyncMock(return_value=None)


def _make_db(scalars_rows=None, scalar_value=None):
    """Build a minimal AsyncSession mock for the integrations router."""
    db = MagicMock()

    # db.scalars(...) → result with .all()
    scalars_result = MagicMock()
    scalars_result.all.return_value = scalars_rows or []
    db.scalars = AsyncMock(return_value=scalars_result)

    # db.scalar(...) → single row or None
    db.scalar = AsyncMock(return_value=scalar_value)

    db.commit = AsyncMock()
    return db


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def provider():
    return _FakeProvider()


@pytest.fixture
def client(provider, monkeypatch):
    """TestClient with auth + DB stubbed out and registry pointing at the
    single fake provider."""

    async def _override_user():
        return _FakeUser()

    async def _override_db():
        yield _make_db()

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db

    # Patch registry to only contain our test provider
    monkeypatch.setattr(
        routers_module, "INTEGRATION_REGISTRY", {provider.slug: provider}
    )
    monkeypatch.setattr(
        routers_module, "get_provider", lambda slug: {provider.slug: provider}.get(slug)
    )

    yield TestClient(app)
    app.dependency_overrides.clear()


def _client_with_db(provider, db, monkeypatch):
    """Return a TestClient that uses the given db mock instead of the fixture default."""

    async def _override_user():
        return _FakeUser()

    async def _override_db():
        yield db

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db

    monkeypatch.setattr(
        routers_module, "INTEGRATION_REGISTRY", {provider.slug: provider}
    )
    monkeypatch.setattr(
        routers_module, "get_provider", lambda slug: {provider.slug: provider}.get(slug)
    )

    return TestClient(app)


# ── GET /api/v1/integrations — list ───────────────────────────────────────


def test_list_integrations_no_db_row_returns_disconnected(provider, monkeypatch):
    db = _make_db(scalars_rows=[])  # no persisted integration for this user
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.get("/api/v1/integrations")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["data"][0]
    assert item["slug"] == "test-provider"
    assert item["status"] == "disconnected"
    assert item["last_synced_at"] is None
    assert item["last_error"] is None

    app.dependency_overrides.clear()


def test_list_integrations_with_db_row_calls_provider_status(provider, monkeypatch):
    integration = _FakeIntegration()
    db = _make_db(scalars_rows=[integration])
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.get("/api/v1/integrations")

    assert resp.status_code == 200
    item = resp.json()["data"][0]
    assert item["status"] == "connected"
    assert item["last_synced_at"] == "2024-01-01T00:00:00Z"
    assert item["last_error"] is None

    provider.status.assert_awaited_once()
    app.dependency_overrides.clear()


def test_list_integrations_provider_status_raises_sets_error_not_500(
    provider, monkeypatch
):
    """Regression guard: a provider whose status() raises must not blank the
    whole list or 500 — it must surface as status='error' with last_error set
    so the other providers still render (BLE001 exception in the router).
    """
    integration = _FakeIntegration()
    provider.status = AsyncMock(side_effect=RuntimeError("upstream timeout"))
    db = _make_db(scalars_rows=[integration])
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.get("/api/v1/integrations")

    assert resp.status_code == 200
    item = resp.json()["data"][0]
    assert item["status"] == "error"
    assert "RuntimeError" in item["last_error"]
    assert item["extra"] == {}

    app.dependency_overrides.clear()


def test_list_integrations_returns_all_providers_even_when_one_fails(
    provider, monkeypatch
):
    """The list length must equal registry size regardless of per-provider status() errors."""
    provider.status = AsyncMock(side_effect=Exception("boom"))
    db = _make_db(scalars_rows=[_FakeIntegration()])
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.get("/api/v1/integrations")

    assert resp.status_code == 200
    assert resp.json()["total"] == 1  # one provider, still listed

    app.dependency_overrides.clear()


# ── POST /api/v1/integrations/{slug}/connect ──────────────────────────────


def test_connect_unknown_slug_returns_404(client):
    resp = client.post("/api/v1/integrations/does-not-exist/connect")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_integration"


def test_connect_known_provider_returns_integration_id(client, provider):
    provider.connect.return_value = ConnectResult(
        integration_id="int-abc", redirect_url=None
    )

    resp = client.post("/api/v1/integrations/test-provider/connect", json={})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["integration_id"] == "int-abc"
    assert data["redirect_url"] is None


def test_connect_oauth_provider_returns_redirect_url(client, provider):
    provider.connect.return_value = ConnectResult(
        integration_id=None, redirect_url="https://provider.example.com/auth"
    )

    resp = client.post("/api/v1/integrations/test-provider/connect", json={})

    assert resp.status_code == 200
    assert resp.json()["data"]["redirect_url"] == "https://provider.example.com/auth"


def test_connect_integration_error_maps_to_400(client, provider):
    provider.connect = AsyncMock(
        side_effect=IntegrationError("invalid_api_key", "The API key is not valid.")
    )

    resp = client.post("/api/v1/integrations/test-provider/connect", json={})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_api_key"


# ── POST /api/v1/integrations/{slug}/disconnect ───────────────────────────


def test_disconnect_unknown_slug_returns_404(client):
    resp = client.post("/api/v1/integrations/ghost/disconnect")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_integration"


def test_disconnect_when_no_integration_row_returns_already_disconnected(
    provider, monkeypatch
):
    db = _make_db(scalar_value=None)  # _find_user_integration returns None
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.post("/api/v1/integrations/test-provider/disconnect")

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "already_disconnected"
    provider.disconnect.assert_not_awaited()

    app.dependency_overrides.clear()


def test_disconnect_when_connected_calls_provider_disconnect_and_returns_disconnected(
    provider, monkeypatch
):
    integration = _FakeIntegration()
    db = _make_db(scalar_value=integration)
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.post("/api/v1/integrations/test-provider/disconnect")

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "disconnected"
    provider.disconnect.assert_awaited_once()

    app.dependency_overrides.clear()


# ── GET /api/v1/integrations/{slug}/status ────────────────────────────────


def test_status_unknown_slug_returns_404(client):
    resp = client.get("/api/v1/integrations/ghost/status")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_integration"


def test_status_when_no_integration_row_returns_disconnected(provider, monkeypatch):
    db = _make_db(scalar_value=None)
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.get("/api/v1/integrations/test-provider/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["slug"] == "test-provider"
    assert data["status"] == "disconnected"
    assert data["last_synced_at"] is None
    assert data["last_error"] is None
    provider.status.assert_not_awaited()

    app.dependency_overrides.clear()


def test_status_when_connected_returns_provider_report(provider, monkeypatch):
    provider.status.return_value = StatusReport(
        status="connected",
        last_synced_at="2024-06-01T12:00:00Z",
        last_error=None,
        extra={"rows": 42},
    )
    integration = _FakeIntegration()
    db = _make_db(scalar_value=integration)
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.get("/api/v1/integrations/test-provider/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "connected"
    assert data["last_synced_at"] == "2024-06-01T12:00:00Z"
    assert data["extra"] == {"rows": 42}

    app.dependency_overrides.clear()


def test_status_when_error_state_surfaces_last_error(provider, monkeypatch):
    provider.status.return_value = StatusReport(
        status="error",
        last_synced_at=None,
        last_error="upstream 503",
        extra={},
    )
    integration = _FakeIntegration(status="error")
    db = _make_db(scalar_value=integration)
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.get("/api/v1/integrations/test-provider/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "error"
    assert data["last_error"] == "upstream 503"

    app.dependency_overrides.clear()


# ── POST /api/v1/integrations/{slug}/sync ─────────────────────────────────


def test_sync_unknown_slug_returns_404(client):
    resp = client.post("/api/v1/integrations/ghost/sync")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_integration"


def test_sync_when_not_connected_returns_400(provider, monkeypatch):
    db = _make_db(scalar_value=None)
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.post("/api/v1/integrations/test-provider/sync")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_connected"

    app.dependency_overrides.clear()


def test_sync_when_connected_returns_result(provider, monkeypatch):
    provider.sync.return_value = SyncResult(
        rows_written=7, summary="7 rows synced", duration_ms=250
    )
    integration = _FakeIntegration()
    db = _make_db(scalar_value=integration)
    tc = _client_with_db(provider, db, monkeypatch)

    resp = tc.post("/api/v1/integrations/test-provider/sync")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["rows_written"] == 7
    assert data["summary"] == "7 rows synced"
    assert data["duration_ms"] == 250

    app.dependency_overrides.clear()
