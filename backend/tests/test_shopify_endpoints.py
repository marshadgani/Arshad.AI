"""Tests for GET /api/v1/shopify/dashboard.

Mirrors the structure of test_whoop_endpoints.py: TestClient with
dependency_overrides for get_current_user / get_db, monkeypatched rate
limiter, and _FakeIntegration / _FakeUser helper classes.

Key contract under test: the endpoint ALWAYS returns HTTP 200 regardless of
upstream state (documented deviation from standard REST, see api.md and the
router module docstring).
"""

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
from src.schemas.shopify import ShopifyDashboard

USER_ID = uuid.uuid4()
INTEGRATION_ID = uuid.uuid4()


class _FakeUser:
    id = USER_ID


class _FakeIntegration:
    def __init__(self, status: str = "connected", config: dict | None = None):
        self.id = INTEGRATION_ID
        self.status = status
        self.last_error = None
        self.config = config or {"shop_domain": "my-store.myshopify.com"}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(shopify_module, "_check_rate_limit", AsyncMock(return_value=None))


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
        shopify_module, "_find_integration", AsyncMock(return_value=integration)
    )


# ── No integration at all ─────────────────────────────────────────────────────


def test_dashboard_no_integration_returns_200_with_connected_false(client, monkeypatch):
    _mock_find_integration(monkeypatch, None)

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    assert resp.json()["data"]["connected"] is False


def test_dashboard_no_integration_does_not_call_get_token(client, monkeypatch):
    _mock_find_integration(monkeypatch, None)
    get_token = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(shopify_module, "_get_token", get_token)

    client.get("/api/v1/shopify/dashboard")

    get_token.assert_not_awaited()


# ── Pre-fetch gate: status == 'expired' ───────────────────────────────────────


def test_dashboard_expired_status_returns_200_with_needs_reauth_true(client, monkeypatch):
    integration = _FakeIntegration(status="expired")
    _mock_find_integration(monkeypatch, integration)
    get_token = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(shopify_module, "_get_token", get_token)

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True
    assert body["needs_reauth"] is True
    get_token.assert_not_awaited()


# ── Cache hit ─────────────────────────────────────────────────────────────────


def test_dashboard_cache_hit_skips_live_fetch(client, monkeypatch):
    integration = _FakeIntegration(status="connected")
    _mock_find_integration(monkeypatch, integration)
    cached_payload = {"connected": True, "needs_reauth": False, "cached_at": "2026-09-11T00:00:00Z"}
    monkeypatch.setattr(shopify_module, "_get_cached", AsyncMock(return_value=cached_payload))
    execute_query = AsyncMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(shopify_module, "_execute_query", execute_query)

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    assert resp.json()["data"]["cached_at"] == "2026-09-11T00:00:00Z"
    execute_query.assert_not_awaited()


# ── Happy path: cache miss → live fetch ───────────────────────────────────────


def test_dashboard_cache_miss_fetches_live_data_and_returns_200(client, monkeypatch):
    integration = _FakeIntegration(
        status="connected",
        config={
            "shop_domain": "my-store.myshopify.com",
            "shop_timezone": "UTC",
            "currency_code": "USD",
            "shop_name": "My Store",
        },
    )
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(shopify_module, "_get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(shopify_module, "_get_token", AsyncMock(return_value="tok"))
    raw = {"orders": [], "orders_count": 0}
    monkeypatch.setattr(shopify_module, "_execute_query", AsyncMock(return_value=raw))
    monkeypatch.setattr(shopify_module, "_mark_healthy", AsyncMock())
    monkeypatch.setattr(shopify_module, "_set_cached", AsyncMock())

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True
    assert body["needs_reauth"] is False


# ── Regression: build_dashboard inside try → parse failure degrades to 200 ───


def test_dashboard_build_dashboard_validation_error_degrades_to_200_not_500(
    client, monkeypatch
):
    """Regression test for the fix that moved dashboards.build_dashboard(...)
    INSIDE the try/except that catches _FETCH_ERRORS.

    Before the fix: a ValueError raised by build_dashboard (e.g. a Pydantic
    ValidationError from a malformed Shopify payload — ValidationError IS a
    ValueError subclass) would propagate uncaught and cause a 500.

    After the fix: it is caught by `except _FETCH_ERRORS` and the endpoint
    degrades gracefully to a 200 response via _failure_response().
    """
    integration = _FakeIntegration(
        status="connected",
        config={
            "shop_domain": "my-store.myshopify.com",
            "shop_timezone": "UTC",
            "currency_code": "USD",
        },
    )
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(shopify_module, "_get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(shopify_module, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(shopify_module, "_execute_query", AsyncMock(return_value={}))

    # Simulate build_dashboard raising a ValueError (which ValidationError inherits).
    import src.services.shopify.dashboard as dash_module
    monkeypatch.setattr(
        dash_module,
        "build_dashboard",
        MagicMock(side_effect=ValueError("simulated malformed payload")),
    )
    monkeypatch.setattr(shopify_module, "_apply_error_status", AsyncMock())

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True


# ── Fetch-layer httpx.HTTPError → _failure_response → 200 ───────────────────


def test_dashboard_httpx_error_routes_through_failure_response_and_returns_200(
    client, monkeypatch
):
    integration = _FakeIntegration(status="connected")
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(shopify_module, "_get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(shopify_module, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        shopify_module,
        "_execute_query",
        AsyncMock(side_effect=httpx.ConnectTimeout("timed out")),
    )
    monkeypatch.setattr(shopify_module, "_apply_error_status", AsyncMock())

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True


def test_dashboard_integration_error_with_reauth_code_returns_needs_reauth(
    client, monkeypatch
):
    integration = _FakeIntegration(status="connected")
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(shopify_module, "_get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(
        shopify_module,
        "_get_token",
        AsyncMock(side_effect=IntegrationError("refresh_failed", "token expired")),
    )
    monkeypatch.setattr(shopify_module, "_apply_error_status", AsyncMock())

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True
    assert body["needs_reauth"] is True


# ── Successful fetch resets integration to healthy ────────────────────────────


def test_dashboard_successful_fetch_calls_mark_healthy(client, monkeypatch):
    integration = _FakeIntegration(
        status="error",
        config={
            "shop_domain": "my-store.myshopify.com",
            "shop_timezone": "UTC",
            "currency_code": "USD",
        },
    )
    _mock_find_integration(monkeypatch, integration)
    monkeypatch.setattr(shopify_module, "_get_cached", AsyncMock(return_value=None))
    monkeypatch.setattr(shopify_module, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(shopify_module, "_execute_query", AsyncMock(return_value={"orders": [], "orders_count": 0}))
    mark_healthy = AsyncMock()
    monkeypatch.setattr(shopify_module, "_mark_healthy", mark_healthy)
    monkeypatch.setattr(shopify_module, "_set_cached", AsyncMock())

    resp = client.get("/api/v1/shopify/dashboard")

    assert resp.status_code == 200
    mark_healthy.assert_awaited_once()
