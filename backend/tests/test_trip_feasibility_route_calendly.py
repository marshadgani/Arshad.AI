"""FEAT-180 — trip-feasibility route: Calendly integration tests.

Uses the same TestClient pattern as test_trip_feasibility_route_infra.py;
the project has no async_client fixture so we rely on fastapi.testclient.TestClient
with dependency overrides and monkeypatching.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.api.v1 import trip_feasibility as route
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.services.shopify.providers import CalendlyFetchResult

PAYLOAD = {"start_date": "2026-11-01", "end_date": "2026-11-07"}


class _FakeUser:
    id = uuid.uuid4()


@pytest.fixture
def base_client(monkeypatch):
    async def _user():
        return _FakeUser()

    async def _db():
        db = MagicMock()
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    monkeypatch.setattr(route, "_check_rate_limit", AsyncMock())
    monkeypatch.setattr(route, "_find_integration", AsyncMock(return_value=None))
    monkeypatch.setattr(
        route, "_list_calendar_events", AsyncMock(return_value={"items": []})
    )
    monkeypatch.setattr(
        route, "_find_infra_integrations", AsyncMock(return_value=(None, None))
    )

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_tc201_calendly_not_connected_verdict_is_unknown(monkeypatch, base_client):
    """TC-201: nothing connected -> verdict is exactly unknown."""
    monkeypatch.setattr(
        route.providers,
        "resolve_calendly",
        AsyncMock(return_value=CalendlyFetchResult(connected=False)),
    )
    resp = base_client.post("/api/v1/trip-feasibility", json=PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["verdict"] == "unknown"
    assert data["calendly_connected"] is False


def test_tc202_calendly_needs_reauth_verdict_is_unknown(monkeypatch, base_client):
    """TC-202: Calendly token expired → verdict degrades to 'unknown'."""
    monkeypatch.setattr(
        route.providers,
        "resolve_calendly",
        AsyncMock(return_value=CalendlyFetchResult(connected=True, needs_reauth=True)),
    )
    resp = base_client.post("/api/v1/trip-feasibility", json=PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["calendly_connected"] is True
    assert data["calendly_needs_reauth"] is True
    assert data["verdict"] == "unknown"


def test_tc203_calendly_partial_failure_is_always_200(monkeypatch, base_client):
    """TC-203: Calendly partial failure never causes a non-200 response."""
    monkeypatch.setattr(
        route.providers,
        "resolve_calendly",
        AsyncMock(
            return_value=CalendlyFetchResult(connected=True, partial_failure=True)
        ),
    )
    resp = base_client.post("/api/v1/trip-feasibility", json=PAYLOAD)
    assert resp.status_code == 200
