"""Integration-shape tests for the three Whoop data-read endpoints.

Exercises the pre-fetch reauth gate, the mid-fetch exception -> reauth
mapping, the self-healing status reset, and the wire-shape contract
(200+needs_reauth for /dashboard, 409 whoop_reauth_required for the
other two). DB and rate-limiter are stubbed; only whoop.py's own
control flow is under test.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from src.api.v1 import whoop as whoop_module
from src.auth.dependencies import get_current_user
from src.integrations.base import IntegrationError
from src.main import app
from src.models.database import get_db

USER_ID = uuid.uuid4()


class _FakeUser:
    id = USER_ID


class _FakeIntegration:
    def __init__(self, status: str = "connected", config: dict | None = None):
        self.status = status
        self.last_error = None
        self.config = config or {}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(whoop_module, "_check_rate_limit", AsyncMock(return_value=None))


@pytest.fixture
def client(monkeypatch):
    async def _override_user():
        return _FakeUser()

    async def _override_db():
        db = MagicMock()
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mock_find_integration(monkeypatch, integration):
    monkeypatch.setattr(
        whoop_module, "_find_whoop_integration", AsyncMock(return_value=integration)
    )


# ── no integration at all ──────────────────────────────────────────────────


def test_dashboard_no_integration_returns_disconnected(client, monkeypatch):
    _mock_find_integration(monkeypatch, None)
    resp = client.get("/api/v1/whoop/dashboard")
    assert resp.status_code == 200
    assert resp.json()["data"]["connected"] is False


def test_hrv_trend_no_integration_returns_404(client, monkeypatch):
    _mock_find_integration(monkeypatch, None)
    resp = client.get("/api/v1/whoop/hrv-trend")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "whoop_not_connected"


def test_workouts_no_integration_returns_404(client, monkeypatch):
    _mock_find_integration(monkeypatch, None)
    resp = client.get("/api/v1/whoop/workouts")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "whoop_not_connected"


# ── pre-fetch gate: status == 'expired' short-circuits before any token/HTTP work ──


def test_dashboard_prefetch_gate_returns_needs_reauth_without_upstream_call(
    client, monkeypatch
):
    integration = _FakeIntegration(status="expired")
    _mock_find_integration(monkeypatch, integration)
    get_token = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(whoop_module, "_get_token", get_token)

    resp = client.get("/api/v1/whoop/dashboard")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True
    assert body["needs_reauth"] is True
    get_token.assert_not_awaited()


def test_dashboard_mid_fetch_transient_upstream_error_returns_200_degraded(
    client, monkeypatch
):
    """Regression guard for the always-200 contract bug: a transient
    upstream failure (network timeout, Whoop 5xx) must never 502 on
    /dashboard — it previously did, because the old except block called
    _persist_fetch_failure, which raises whenever needs_reauth is False.
    """
    integration = _FakeIntegration(status="connected")
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(whoop_module, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        whoop_module,
        "_fetch_dashboard_data",
        AsyncMock(side_effect=httpx.ConnectTimeout("timed out")),
    )

    resp = client.get("/api/v1/whoop/dashboard")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True
    assert body["needs_reauth"] is False
    assert body["degraded"] is True
    assert body["recovery"] is None


def test_dashboard_mid_fetch_401_returns_needs_reauth_not_degraded(client, monkeypatch):
    integration = _FakeIntegration(status="connected")
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(whoop_module, "_get_token", AsyncMock(return_value="tok"))

    response = MagicMock()
    response.status_code = 401
    exc = httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=response)
    monkeypatch.setattr(
        whoop_module, "_fetch_dashboard_data", AsyncMock(side_effect=exc)
    )

    resp = client.get("/api/v1/whoop/dashboard")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["needs_reauth"] is True
    assert body["degraded"] is False


def test_hrv_trend_prefetch_gate_returns_409(client, monkeypatch):
    integration = _FakeIntegration(status="expired")
    _mock_find_integration(monkeypatch, integration)
    get_token = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(whoop_module, "_get_token", get_token)

    resp = client.get("/api/v1/whoop/hrv-trend")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "whoop_reauth_required"
    get_token.assert_not_awaited()


def test_workouts_prefetch_gate_returns_409(client, monkeypatch):
    integration = _FakeIntegration(status="expired")
    _mock_find_integration(monkeypatch, integration)
    get_token = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(whoop_module, "_get_token", get_token)

    resp = client.get("/api/v1/whoop/workouts")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "whoop_reauth_required"
    get_token.assert_not_awaited()


# ── mid-fetch exceptions ───────────────────────────────────────────────────


def test_hrv_trend_mid_fetch_integration_error_maps_to_reauth(client, monkeypatch):
    integration = _FakeIntegration(status="connected")
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(
        whoop_module,
        "_get_token",
        AsyncMock(side_effect=IntegrationError("refresh_failed", "expired")),
    )

    resp = client.get("/api/v1/whoop/hrv-trend")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "whoop_reauth_required"
    assert integration.status == "expired"


def test_workouts_mid_fetch_upstream_500_maps_to_502(client, monkeypatch):
    integration = _FakeIntegration(status="connected")
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(whoop_module, "_get_token", AsyncMock(return_value="tok"))

    response = MagicMock(spec=httpx.Response)
    response.status_code = 500
    request = MagicMock(spec=httpx.Request)
    monkeypatch.setattr(
        whoop_module,
        "_whoop_get",
        AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "boom", request=request, response=response
            )
        ),
    )

    resp = client.get("/api/v1/whoop/workouts")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "whoop_api_error"
    assert integration.status == "error"


def test_status_error_self_heals_on_next_successful_fetch(client, monkeypatch):
    """M-2 guard: an integration left in status='error' by a prior failure
    must reset to 'connected' on the next successful upstream fetch,
    rather than blanking the page forever.
    """
    integration = _FakeIntegration(status="error")
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(whoop_module, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        whoop_module, "_whoop_get", AsyncMock(return_value={"records": []})
    )

    resp = client.get("/api/v1/whoop/workouts")
    assert resp.status_code == 200
    assert integration.status == "connected"
    assert integration.last_error is None


# ── W-2: nested profile read ────────────────────────────────────────────────


def test_dashboard_reads_nested_profile_first_name(client, monkeypatch):
    integration = _FakeIntegration(
        status="connected", config={"profile": {"first_name": "Arshad"}}
    )
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(whoop_module, "_get_token", AsyncMock(return_value="tok"))
    empty = {"records": []}
    monkeypatch.setattr(
        whoop_module,
        "_fetch_dashboard_data",
        AsyncMock(return_value=(empty, empty, empty)),
    )

    resp = client.get("/api/v1/whoop/dashboard")
    assert resp.status_code == 200
    assert resp.json()["data"]["user_first_name"] == "Arshad"
