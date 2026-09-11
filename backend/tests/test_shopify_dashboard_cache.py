"""Tests for backend/src/services/shopify/dashboard.py and cache.py.

dashboard.py is pure given an Integration / ShopContext — tested with
lightweight fakes, no DB.

cache.py wraps Redis with fail-open semantics — tested by mocking
get_redis() so no real Redis connection is required, with RedisError
injected to verify the degrade-gracefully contract.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.exceptions

from src.services.shopify.cache import (
    DASHBOARD_TTL_SECONDS,
    dashboard_cache_key,
    del_dashboard_cache,
    get_cached_dashboard,
    set_cached_dashboard,
)
from src.services.shopify.dashboard import build_dashboard, shell_dashboard
from src.services.shopify.state import ShopContext


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_integration(config: dict | None = None) -> MagicMock:
    """Minimal Integration stand-in that state.shop_presentation() can read."""
    integration = MagicMock()
    integration.config = config or {}
    return integration


def _make_shop_context(**kwargs) -> ShopContext:
    defaults = {
        "shop": "my-store.myshopify.com",
        "timezone": "America/New_York",
        "currency_code": "USD",
        "shop_name": "My Store",
    }
    defaults.update(kwargs)
    return ShopContext(**defaults)


# ── shell_dashboard ────────────────────────────────────────────────────────


def test_shell_dashboard_sets_needs_reauth_true():
    integration = _make_integration({"shop_name": "Test", "currency_code": "GBP"})

    result = shell_dashboard(integration, needs_reauth=True)

    assert result.needs_reauth is True
    assert result.connected is True


def test_shell_dashboard_sets_needs_reauth_false():
    integration = _make_integration()

    result = shell_dashboard(integration, needs_reauth=False)

    assert result.needs_reauth is False


def test_shell_dashboard_carries_through_shop_name():
    integration = _make_integration({"shop_name": "Acme Corp"})

    result = shell_dashboard(integration, needs_reauth=False)

    assert result.shop_name == "Acme Corp"


def test_shell_dashboard_carries_through_currency_and_timezone():
    integration = _make_integration(
        {"currency_code": "EUR", "shop_timezone": "Europe/Berlin"}
    )

    result = shell_dashboard(integration, needs_reauth=False)

    assert result.currency_code == "EUR"
    assert result.timezone == "Europe/Berlin"


def test_shell_dashboard_tolerates_empty_config():
    """A partially-populated integration must never raise."""
    integration = _make_integration({})

    result = shell_dashboard(integration, needs_reauth=True)

    assert result.connected is True
    assert result.shop_name is None
    assert result.currency_code is None


def test_shell_dashboard_has_no_live_revenue_fields():
    """The shell shape must never include revenue — it has no live data."""
    integration = _make_integration({"shop_name": "X"})

    result = shell_dashboard(integration, needs_reauth=False)

    assert result.revenue_amount is None
    assert result.order_count is None
    assert result.recent_orders == []


# ── build_dashboard ────────────────────────────────────────────────────────


def test_build_dashboard_attaches_shop_name_from_context():
    ctx = _make_shop_context(shop_name="Flagship Store")
    raw = {"orders": [], "orders_count": 0}

    result = build_dashboard(raw, ctx, as_of="2026-09-11T10:00:00Z")

    assert result.shop_name == "Flagship Store"


def test_build_dashboard_attaches_timezone_from_context():
    ctx = _make_shop_context(timezone="Asia/Tokyo")
    raw = {"orders": [], "orders_count": 0}

    result = build_dashboard(raw, ctx, as_of="2026-09-11T10:00:00Z")

    assert result.timezone == "Asia/Tokyo"


def test_build_dashboard_attaches_as_of_timestamp():
    ctx = _make_shop_context()
    raw = {"orders": [], "orders_count": 0}
    stamp = "2026-09-11T14:22:00Z"

    result = build_dashboard(raw, ctx, as_of=stamp)

    assert result.as_of == stamp


def test_build_dashboard_uses_currency_code_from_context():
    ctx = _make_shop_context(currency_code="CAD")
    raw = {"orders": [], "orders_count": 0}

    result = build_dashboard(raw, ctx, as_of="2026-09-11T10:00:00Z")

    assert result.currency_code == "CAD"


def test_build_dashboard_parses_orders_from_raw():
    ctx = _make_shop_context()
    raw = {
        "orders": [
            {
                "id": "gid://shopify/Order/1",
                "name": "#1001",
                "createdAt": "2026-09-11T09:00:00Z",
                "currentTotalPriceSet": {
                    "shopMoney": {"amount": "50.00", "currencyCode": "USD"}
                },
            }
        ],
        "orders_count": 1,
    }

    result = build_dashboard(raw, ctx, as_of="2026-09-11T10:00:00Z")

    assert result.revenue_amount == "50.00"
    assert len(result.recent_orders) == 1


# ── dashboard_cache_key ────────────────────────────────────────────────────


def test_dashboard_cache_key_format():
    key = dashboard_cache_key("abc-123")

    assert key == "shopify:dash:abc-123"


def test_dashboard_cache_key_is_stable():
    assert dashboard_cache_key("x") == dashboard_cache_key("x")


# ── get_cached_dashboard ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_cached_dashboard_returns_none_on_cache_miss():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        result = await get_cached_dashboard("id-1")

    assert result is None


@pytest.mark.asyncio
async def test_get_cached_dashboard_returns_parsed_dict_on_hit():
    payload = {"connected": True, "revenue_amount": "99.00"}
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(payload).encode()

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        result = await get_cached_dashboard("id-1")

    assert result == payload


@pytest.mark.asyncio
async def test_get_cached_dashboard_returns_none_on_redis_error():
    """Fail-open: a Redis outage must not propagate to the caller."""
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = redis.exceptions.ConnectionError("down")

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        result = await get_cached_dashboard("id-1")

    assert result is None


@pytest.mark.asyncio
async def test_get_cached_dashboard_returns_none_on_invalid_json():
    """Corrupted cache entry must degrade to a miss, not raise."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = b"not-valid-json{"

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        result = await get_cached_dashboard("id-1")

    assert result is None


@pytest.mark.asyncio
async def test_get_cached_dashboard_uses_correct_cache_key():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        await get_cached_dashboard("my-integration-id")

    mock_redis.get.assert_called_once_with("shopify:dash:my-integration-id")


# ── set_cached_dashboard ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_cached_dashboard_writes_json_with_ttl():
    mock_redis = AsyncMock()
    data = {"connected": True}

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        await set_cached_dashboard("id-1", data)

    mock_redis.set.assert_called_once_with(
        "shopify:dash:id-1",
        json.dumps(data),
        ex=DASHBOARD_TTL_SECONDS,
    )


@pytest.mark.asyncio
async def test_set_cached_dashboard_accepts_custom_ttl():
    mock_redis = AsyncMock()

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        await set_cached_dashboard("id-2", {}, ttl=60)

    _, kwargs = mock_redis.set.call_args
    assert kwargs.get("ex") == 60 or mock_redis.set.call_args[0][2] == 60


@pytest.mark.asyncio
async def test_set_cached_dashboard_does_not_raise_on_redis_error():
    """Fail-open: a write failure must be swallowed silently."""
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = redis.exceptions.TimeoutError("timeout")

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        # Must not raise
        await set_cached_dashboard("id-1", {"connected": True})


# ── del_dashboard_cache ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_del_dashboard_cache_calls_delete_with_correct_key():
    mock_redis = AsyncMock()

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        await del_dashboard_cache("id-99")

    mock_redis.delete.assert_called_once_with("shopify:dash:id-99")


@pytest.mark.asyncio
async def test_del_dashboard_cache_does_not_raise_on_redis_error():
    """Fail-open: a delete failure must be swallowed, not propagate."""
    mock_redis = AsyncMock()
    mock_redis.delete.side_effect = redis.exceptions.ConnectionError("down")

    with patch("src.services.shopify.cache.get_redis", return_value=mock_redis):
        # Must not raise
        await del_dashboard_cache("id-99")
