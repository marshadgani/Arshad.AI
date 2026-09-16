"""Tests for GET /api/v1/shopify/insights in backend/src/api/v1/shopify.py.

Mirrors the structure of test_shopify_endpoints.py: TestClient against the
real `app` (so the project's custom HTTPException handler / error envelope
is exercised), with collaborators monkeypatched at module scope.

Key contract under test: unlike /dashboard, /insights is NOT always-200 —
it answers honest 404/409/503 and never 401.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from src.api.v1 import shopify as shopify_module
from src.auth.dependencies import get_current_user
from src.integrations.base import IntegrationError
from src.main import app
from src.models.database import get_db

USER_ID = uuid.uuid4()
INTEGRATION_ID = uuid.uuid4()


class _FakeUser:
    id = USER_ID


class _FakeIntegration:
    def __init__(self, status: str = "connected", config: dict | None = None):
        self.id = INTEGRATION_ID
        self.status = status
        self.last_error = None
        # `is None`, not `or`: an explicitly-empty config is a real case
        # under test (a record whose shop domain never persisted), and `or`
        # would silently swap it for the fully-populated default.
        self.config = (
            {
                "shop_domain": "my-store.myshopify.com",
                "shop_timezone": "UTC",
                "currency_code": "USD",
            }
            if config is None
            else config
        )


_EMPTY_RAW = {
    "orders": [],
    "truncated": False,
    "covered_through": None,
    "partial_failures": [],
}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(
        shopify_module, "_check_rate_limit", AsyncMock(return_value=None)
    )


@pytest.fixture(autouse=True)
def _default_collaborators(monkeypatch):
    monkeypatch.setattr(shopify_module, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        shopify_module, "_get_cached_insights", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(shopify_module, "_set_cached_insights", AsyncMock())
    monkeypatch.setattr(shopify_module, "_mark_healthy", AsyncMock())
    monkeypatch.setattr(shopify_module, "_apply_error_status", AsyncMock())
    monkeypatch.setattr(
        shopify_module, "_execute_insights_query", AsyncMock(return_value=_EMPTY_RAW)
    )


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


def _mock_find_integration(monkeypatch, integration):
    monkeypatch.setattr(
        shopify_module, "_find_integration", AsyncMock(return_value=integration)
    )


# ── No integration ─────────────────────────────────────────────────────────


def test_no_integration_returns_404(client, monkeypatch):
    _mock_find_integration(monkeypatch, None)

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "shopify_not_connected"


def test_no_integration_never_returns_401(client, monkeypatch):
    _mock_find_integration(monkeypatch, None)

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code != 401


# ── Pre-fetch gate: status == 'expired' ─────────────────────────────────────


def test_expired_status_returns_409(client, monkeypatch):
    _mock_find_integration(monkeypatch, _FakeIntegration(status="expired"))
    get_token = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(shopify_module, "_get_token", get_token)

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "shopify_reauth_required"
    get_token.assert_not_awaited()


def test_missing_shop_domain_returns_409_not_500(client, monkeypatch):
    """A record whose shop domain never persisted must reach the reauth
    branch, not escape as an internal_error.

    state.shop_context raises IntegrationError("shopify_shop_missing"),
    which state.REAUTH_CODES classifies as reauth — so it has to be raised
    inside the route's fetch guard. Regression test for it being computed
    outside that guard, where main.py's catch-all turned it into a 500.
    """
    _mock_find_integration(monkeypatch, _FakeIntegration(config={}))

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "shopify_reauth_required"


# ── Upstream failure classification ─────────────────────────────────────────


def test_reauth_classified_exception_returns_409_and_applies_status(
    client, monkeypatch
):
    _mock_find_integration(monkeypatch, _FakeIntegration())
    monkeypatch.setattr(
        shopify_module,
        "_execute_insights_query",
        AsyncMock(side_effect=IntegrationError("not_connected", "boom")),
    )
    apply_status = AsyncMock()
    monkeypatch.setattr(shopify_module, "_apply_error_status", apply_status)

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "shopify_reauth_required"
    apply_status.assert_awaited_once()


def test_httpx_error_returns_503(client, monkeypatch):
    _mock_find_integration(monkeypatch, _FakeIntegration())
    monkeypatch.setattr(
        shopify_module,
        "_execute_insights_query",
        AsyncMock(side_effect=httpx.ConnectError("down")),
    )

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "shopify_upstream_unavailable"


def test_timeout_returns_503(client, monkeypatch):
    _mock_find_integration(monkeypatch, _FakeIntegration())
    monkeypatch.setattr(
        shopify_module,
        "_execute_insights_query",
        AsyncMock(side_effect=asyncio.TimeoutError()),
    )

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code == 503


def test_never_returns_401_on_upstream_failure(client, monkeypatch):
    _mock_find_integration(monkeypatch, _FakeIntegration())
    monkeypatch.setattr(
        shopify_module,
        "_execute_insights_query",
        AsyncMock(side_effect=httpx.ConnectError("down")),
    )

    resp = client.get("/api/v1/shopify/insights")

    assert resp.status_code != 401


# ── Success path ─────────────────────────────────────────────────────────


def test_success_marks_healthy_and_caches(client, monkeypatch):
    _mock_find_integration(monkeypatch, _FakeIntegration())
    mark_healthy = AsyncMock()
    set_cached = AsyncMock()
    monkeypatch.setattr(shopify_module, "_mark_healthy", mark_healthy)
    monkeypatch.setattr(shopify_module, "_set_cached_insights", set_cached)

    resp = client.get("/api/v1/shopify/insights?days=14")

    assert resp.status_code == 200
    assert resp.json()["data"]["cached_at"] is not None
    mark_healthy.assert_awaited_once()
    set_cached.assert_awaited_once()


def test_cache_hit_short_circuits_token_and_upstream_fetch(client, monkeypatch):
    cached_payload = {
        "days": 14,
        "currency_code": "USD",
        "timezone": "UTC",
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
        "points": [],
        "truncated": False,
        "covered_through": None,
        "partial_failures": [],
        "cached_at": "2026-09-14T00:00:00+00:00",
    }
    _mock_find_integration(monkeypatch, _FakeIntegration())
    monkeypatch.setattr(
        shopify_module, "_get_cached_insights", AsyncMock(return_value=cached_payload)
    )
    get_token = AsyncMock(side_effect=AssertionError("must not be called"))
    exec_query = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(shopify_module, "_get_token", get_token)
    monkeypatch.setattr(shopify_module, "_execute_insights_query", exec_query)

    resp = client.get("/api/v1/shopify/insights?days=14")

    assert resp.status_code == 200
    assert resp.json()["data"] == cached_payload
    get_token.assert_not_awaited()
    exec_query.assert_not_awaited()


def test_days_14_and_30_use_different_cache_keys(client, monkeypatch):
    _mock_find_integration(monkeypatch, _FakeIntegration())
    get_cached = AsyncMock(return_value=None)
    monkeypatch.setattr(shopify_module, "_get_cached_insights", get_cached)

    client.get("/api/v1/shopify/insights?days=14")
    client.get("/api/v1/shopify/insights?days=30")

    days_requested = [call.args[1] for call in get_cached.await_args_list]
    assert 14 in days_requested
    assert 30 in days_requested


def test_invalid_days_returns_422(client, monkeypatch):
    _mock_find_integration(monkeypatch, _FakeIntegration())

    resp = client.get("/api/v1/shopify/insights?days=9")

    assert resp.status_code == 422
