"""Integration tests for GET /api/v1/dashboard/weather (FEAT-138).

``test_weather_service.py`` exercises ``get_weather_dashboard`` directly;
this file exercises the actual FastAPI route on top of it — dependency
injection, the ``{"data": {...}}`` envelope, the always-200 contract, and
the auth gate — none of which the service-level tests can catch (e.g. a
wrong import path, a missing ``by_alias=True``, or a route that forgot the
auth dependency entirely).

Pattern follows test_whoop_endpoints.py: get_weather_dashboard is patched
at its import site inside the dashboard router module.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.schemas.dashboard import WeatherResponse

USER_ID = uuid.uuid4()


class _FakeUser:
    id = USER_ID


@pytest.fixture
def client():
    async def _override_user():
        return _FakeUser()

    async def _override_db():
        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        yield db

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mock_service(monkeypatch, response: WeatherResponse):
    monkeypatch.setattr(
        "src.api.v1.dashboard.get_weather_dashboard",
        AsyncMock(return_value=response),
    )


# ── always-200 contract across every service state ─────────────────────────


@pytest.mark.parametrize(
    "weather_response",
    [
        WeatherResponse(connected=False),
        WeatherResponse(connected=True, temp="22 °C", condition="Sunny", city="Paris"),
        WeatherResponse(connected=True, needs_reauth=True),
        WeatherResponse(connected=True, degraded=True),
    ],
)
def test_weather_always_returns_http_200(client, monkeypatch, weather_response):
    _mock_service(monkeypatch, weather_response)

    resp = client.get("/api/v1/dashboard/weather")

    assert resp.status_code == 200


# ── envelope shape ──────────────────────────────────────────────────────────


def test_response_wraps_payload_in_data_envelope(client, monkeypatch):
    _mock_service(
        monkeypatch,
        WeatherResponse(connected=True, temp="10 °C", condition="Fog", city="London"),
    )

    body = client.get("/api/v1/dashboard/weather").json()

    assert set(body.keys()) == {"data"}
    assert isinstance(body["data"], dict)


def test_response_data_has_every_schema_field(client, monkeypatch):
    _mock_service(
        monkeypatch,
        WeatherResponse(connected=True, temp="18 °C", condition="Clear", city="Berlin"),
    )

    data = client.get("/api/v1/dashboard/weather").json()["data"]

    for field in ("connected", "needs_reauth", "degraded", "temp", "condition", "city"):
        assert field in data


def test_response_never_contains_an_error_key_for_weather_specific_states(
    client, monkeypatch
):
    """Weather-specific degradation (needs_reauth/degraded) is a 200 with
    flags, not the {"error": {...}} shape reserved for 4xx/5xx failures."""
    _mock_service(monkeypatch, WeatherResponse(connected=True, degraded=True))

    body = client.get("/api/v1/dashboard/weather").json()

    assert "error" not in body


# ── branch-specific field values reach the wire correctly ──────────────────


def test_live_success_reaches_the_response_body(client, monkeypatch):
    _mock_service(
        monkeypatch,
        WeatherResponse(connected=True, temp="25 °C", condition="Sunny", city="Madrid"),
    )

    data = client.get("/api/v1/dashboard/weather").json()["data"]

    assert data == {
        "connected": True,
        "needs_reauth": False,
        "degraded": False,
        "temp": "25 °C",
        "condition": "Sunny",
        "city": "Madrid",
    }


def test_needs_reauth_state_has_null_payload_on_the_wire(client, monkeypatch):
    _mock_service(monkeypatch, WeatherResponse(connected=True, needs_reauth=True))

    data = client.get("/api/v1/dashboard/weather").json()["data"]

    assert data["needs_reauth"] is True
    assert data["temp"] is None
    assert data["city"] is None


def test_degraded_state_has_null_payload_on_the_wire(client, monkeypatch):
    _mock_service(monkeypatch, WeatherResponse(connected=True, degraded=True))

    data = client.get("/api/v1/dashboard/weather").json()["data"]

    assert data["degraded"] is True
    assert data["temp"] is None


def test_never_connected_returns_an_all_null_disconnected_tile(client, monkeypatch):
    _mock_service(monkeypatch, WeatherResponse(connected=False))

    data = client.get("/api/v1/dashboard/weather").json()["data"]

    assert data == {
        "connected": False,
        "needs_reauth": False,
        "degraded": False,
        "temp": None,
        "condition": None,
        "city": None,
    }


# ── the route actually calls the service with the authenticated user ──────


def test_route_calls_service_with_current_user_id(client, monkeypatch):
    mock_service = AsyncMock(return_value=WeatherResponse(connected=False))
    monkeypatch.setattr("src.api.v1.dashboard.get_weather_dashboard", mock_service)

    client.get("/api/v1/dashboard/weather")

    mock_service.assert_awaited_once()
    args, _ = mock_service.await_args
    assert args[0] == USER_ID


# ── auth contract ────────────────────────────────────────────────────────


def test_weather_without_auth_returns_401():
    # No `with` block: entering TestClient as a context manager runs the
    # app's lifespan (DB connectivity check), which requires a live
    # Postgres this test suite does not provision. A plain TestClient
    # dispatches requests without running lifespan, which is all a
    # dependency-level 401 check needs.
    unauthenticated_client = TestClient(app)
    resp = unauthenticated_client.get("/api/v1/dashboard/weather")

    assert resp.status_code == 401



# ── SEC: per-user rate limit on the only dashboard route with third-party
# egress ───────────────────────────────────────────────────────────────────


def test_weather_endpoint_enforces_per_user_rate_limit(client, monkeypatch):
    """A cache miss on this route becomes an outbound OpenWeatherMap call, so
    the endpoint must pass through enforce_rate_limit keyed on the caller."""
    _mock_service(monkeypatch, WeatherResponse(connected=False))
    limiter = AsyncMock(return_value=None)
    monkeypatch.setattr("src.api.v1.dashboard.enforce_rate_limit", limiter)

    resp = client.get("/api/v1/dashboard/weather")

    assert resp.status_code == 200
    assert limiter.await_count == 1
    kwargs = limiter.await_args.kwargs
    assert kwargs["bucket"] == "dashboard_weather"
    assert kwargs["identity"] == str(USER_ID)
    assert kwargs["limit"] > 0
    assert kwargs["window_seconds"] > 0
