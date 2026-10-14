"""FEAT-179 route-level infra tests: always-200, infra conflicts, stale/truncated flags,
not-connected in unavailable_sources, no live HTTP calls."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.api.v1 import trip_feasibility as route
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db

AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
BODY = {"start_date": "2026-06-10", "end_date": "2026-06-14"}
SYNCED_NOW = datetime.now(timezone.utc).isoformat()
SYNCED_STALE = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()


class _FakeUser:
    id = uuid.uuid4()


def _make_row(slug, config, status="connected"):
    row = MagicMock()
    row.slug = slug
    row.config = config
    row.status = status
    return row


def _render_row(services=None, synced_at=None, truncated=False):
    return _make_row(
        "render",
        {
            "services": services or [],
            "synced_at": synced_at or SYNCED_NOW,
            "services_truncated": truncated,
        },
    )


def _supabase_row(projects=None, synced_at=None):
    return _make_row(
        "supabase",
        {
            "projects": projects or [],
            "synced_at": synced_at or SYNCED_NOW,
        },
    )


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


def test_route_always_returns_200(base_client):
    resp = base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "verdict" in data


def test_route_calls_find_infra_integrations(monkeypatch, base_client):
    """Route must invoke _find_infra_integrations on every request."""
    called = []

    async def spy(user_id, db):
        called.append(user_id)
        return (None, None)

    monkeypatch.setattr(route, "_find_infra_integrations", spy)
    base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert len(called) == 1


def test_route_render_suspended_service_in_conflicts(monkeypatch, base_client):
    r = _render_row(
        [{"name": "api", "suspended": "suspended", "latest_deploy_status": "live"}]
    )
    monkeypatch.setattr(
        route, "_find_infra_integrations", AsyncMock(return_value=(r, None))
    )
    resp = base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    infra_conflicts = [c for c in data["conflicts"] if c["type"] == "infrastructure"]
    assert len(infra_conflicts) >= 1
    assert infra_conflicts[0]["provider"] == "render"
    assert data["verdict"] == "no-go"


def test_route_stale_render_gives_unknown_verdict(monkeypatch, base_client):
    r = _render_row(synced_at=SYNCED_STALE)
    monkeypatch.setattr(
        route, "_find_infra_integrations", AsyncMock(return_value=(r, None))
    )
    resp = base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["render_stale"] is True
    assert data["verdict"] == "unknown"


def test_route_truncated_render_sets_truncated_flag(monkeypatch, base_client):
    r = _render_row(truncated=True)
    monkeypatch.setattr(
        route, "_find_infra_integrations", AsyncMock(return_value=(r, None))
    )
    resp = base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["render_truncated"] is True


def test_route_render_not_connected_appears_in_unavailable_sources(base_client):
    resp = base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    unavail_names = [s["name"] for s in data["unavailable_sources"]]
    assert "render_health" in unavail_names
    assert "supabase_health" in unavail_names


def test_route_supabase_inactive_project_in_conflicts(monkeypatch, base_client):
    s = _supabase_row([{"ref": "a", "name": "db", "status": "INACTIVE"}])
    monkeypatch.setattr(
        route, "_find_infra_integrations", AsyncMock(return_value=(None, s))
    )
    resp = base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    infra_conflicts = [c for c in data["conflicts"] if c["type"] == "infrastructure"]
    assert any(c["provider"] == "supabase" for c in infra_conflicts)
    assert data["verdict"] == "no-go"


def test_route_no_live_http_calls_made(monkeypatch, base_client):
    """No real HTTP calls to Render or Supabase APIs during route tests."""
    import httpx

    original_get = httpx.AsyncClient.get

    async def no_external_calls(self, url, **kwargs):
        if "render.com" in url or "supabase.com" in url:
            raise AssertionError(f"Unexpected external call to {url}")
        return await original_get(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", no_external_calls)
    resp = base_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
