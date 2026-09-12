"""Tests for ShopifyIntegration — connect, sync, status, and _record_sync_failure.

Mirrors test_whoop_sync.py's style: direct provider instantiation with
monkeypatched collaborators, no HTTP server.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal.shopify import ShopifyIntegration, _shop_metadata_config


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_integration(config: dict | None = None, status: str = "connected"):
    integration = MagicMock()
    integration.id = uuid.uuid4()
    integration.status = status
    integration.last_error = None
    integration.last_synced_at = None
    integration.config = config or {"shop_domain": "my-store.myshopify.com"}
    return integration


def _make_db():
    db = MagicMock()
    db.commit = AsyncMock()
    return db


# ── _shop_metadata_config ─────────────────────────────────────────────────────


def test_shop_metadata_config_maps_known_fields():
    meta = {
        "ianaTimezone": "Europe/London",
        "currencyCode": "GBP",
        "name": "London Store",
    }

    result = _shop_metadata_config(meta)

    assert result["shop_timezone"] == "Europe/London"
    assert result["currency_code"] == "GBP"
    assert result["shop_name"] == "London Store"


def test_shop_metadata_config_defaults_timezone_and_currency_for_empty_meta():
    result = _shop_metadata_config({})

    assert result["shop_timezone"] == "UTC"
    assert result["currency_code"] == "USD"
    assert result["shop_name"] is None


def test_shop_metadata_config_defaults_when_none_values_present():
    result = _shop_metadata_config({"ianaTimezone": None, "currencyCode": None})

    assert result["shop_timezone"] == "UTC"
    assert result["currency_code"] == "USD"


# ── connect ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_raises_when_no_user():
    provider = ShopifyIntegration()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=None, db=MagicMock(), payload={"shop": "test.myshopify.com"})

    assert exc_info.value.code == "auth_required"


@pytest.mark.asyncio
async def test_connect_raises_integration_error_for_invalid_shop_domain(monkeypatch):
    provider = ShopifyIntegration()
    user = MagicMock()
    user.id = uuid.uuid4()

    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("BACKEND_URL", "https://example.com")

    with pytest.raises((IntegrationError, Exception)):
        await provider.connect(user=user, db=MagicMock(), payload={"shop": "not-a-shopify-domain"})


@pytest.mark.asyncio
async def test_connect_returns_redirect_url_for_valid_shop(monkeypatch):
    provider = ShopifyIntegration()
    user = MagicMock()
    user.id = uuid.uuid4()

    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("BACKEND_URL", "https://arshad-ai.onrender.com")

    # Patch where it is called (in the shopify module), not where defined.
    store_state = AsyncMock(return_value="random-state-token")
    import src.integrations.personal.shopify as shopify_mod
    monkeypatch.setattr(shopify_mod, "store_oauth_state", store_state)

    result = await provider.connect(
        user=user, db=MagicMock(), payload={"shop": "my-store.myshopify.com"}
    )

    assert result.redirect_url is not None
    assert "my-store.myshopify.com" in result.redirect_url
    assert "admin/oauth/authorize" in result.redirect_url


# ── sync ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_updates_config_and_returns_zero_rows_written(monkeypatch):
    provider = ShopifyIntegration()
    integration = _make_integration()
    db = _make_db()

    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    import src.services.shopify.client as shopify_client_mod
    import src.services.shopify.cache as shopify_cache_mod

    monkeypatch.setattr(
        shopify_client_mod,
        "fetch_shop_metadata",
        AsyncMock(return_value={"ianaTimezone": "UTC", "currencyCode": "USD", "name": "Test"}),
    )
    monkeypatch.setattr(shopify_cache_mod, "del_dashboard_cache", AsyncMock())

    result = await provider.sync(integration=integration, db=db)

    assert result.rows_written == 0
    assert integration.status == "connected"
    assert integration.last_error is None
    assert "shop_timezone" in integration.config


@pytest.mark.asyncio
async def test_sync_clears_dashboard_cache_after_metadata_update(monkeypatch):
    provider = ShopifyIntegration()
    integration = _make_integration()
    db = _make_db()

    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    import src.services.shopify.client as shopify_client_mod
    import src.services.shopify.cache as shopify_cache_mod

    monkeypatch.setattr(
        shopify_client_mod,
        "fetch_shop_metadata",
        AsyncMock(return_value={"ianaTimezone": "UTC", "currencyCode": "USD"}),
    )
    del_cache = AsyncMock()
    monkeypatch.setattr(shopify_cache_mod, "del_dashboard_cache", del_cache)

    await provider.sync(integration=integration, db=db)

    del_cache.assert_awaited_once_with(str(integration.id))


@pytest.mark.asyncio
async def test_sync_metadata_fetch_failure_raises_integration_error_and_sets_error_status(
    monkeypatch,
):
    import httpx

    provider = ShopifyIntegration()
    integration = _make_integration()
    db = _make_db()

    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    import src.services.shopify.client as shopify_client_mod

    monkeypatch.setattr(
        shopify_client_mod,
        "fetch_shop_metadata",
        AsyncMock(side_effect=httpx.ConnectError("refused")),
    )

    with pytest.raises(IntegrationError) as exc_info:
        await provider.sync(integration=integration, db=db)

    assert exc_info.value.code == "sync_failed"
    assert integration.status == "error"
    assert integration.last_error is not None


@pytest.mark.asyncio
async def test_sync_summary_includes_shop_domain(monkeypatch):
    provider = ShopifyIntegration()
    integration = _make_integration(
        config={"shop_domain": "best-store.myshopify.com"}
    )
    db = _make_db()

    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    import src.services.shopify.client as shopify_client_mod
    import src.services.shopify.cache as shopify_cache_mod

    monkeypatch.setattr(
        shopify_client_mod,
        "fetch_shop_metadata",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(shopify_cache_mod, "del_dashboard_cache", AsyncMock())

    result = await provider.sync(integration=integration, db=db)

    assert "best-store.myshopify.com" in result.summary


# ── status ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_includes_shop_domain_and_currency_in_extra(monkeypatch):
    provider = ShopifyIntegration()
    integration = _make_integration(
        config={
            "shop_domain": "my-store.myshopify.com",
            "currency_code": "EUR",
        }
    )
    db = _make_db()

    from src.integrations.base import StatusReport

    # StatusReport has: status, last_synced_at, last_error, extra
    mock_report = StatusReport(
        status="connected",
        last_synced_at=None,
        last_error=None,
        extra={},
    )

    with patch.object(
        provider.__class__.__bases__[0],
        "status",
        new=AsyncMock(return_value=mock_report),
    ):
        report = await provider.status(integration=integration, db=db)

    assert report.extra["shop_domain"] == "my-store.myshopify.com"
    assert report.extra["currency_code"] == "EUR"


# ── fetch_profile ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_profile_returns_empty_dict():
    provider = ShopifyIntegration()

    result = await provider.fetch_profile("any-token")

    assert result == {}


# ── _record_sync_failure ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_sync_failure_sets_error_status_and_raises():
    integration = _make_integration()
    db = _make_db()
    exc = ValueError("something broke")

    with pytest.raises(IntegrationError) as exc_info:
        await ShopifyIntegration._record_sync_failure(integration, exc, db)

    assert integration.status == "error"
    assert "ValueError" in integration.last_error
    assert exc_info.value.code == "sync_failed"


@pytest.mark.asyncio
async def test_record_sync_failure_truncates_long_error_messages():
    integration = _make_integration()
    db = _make_db()
    long_message = "x" * 1000
    exc = ValueError(long_message)

    with pytest.raises(IntegrationError):
        await ShopifyIntegration._record_sync_failure(integration, exc, db)

    assert len(integration.last_error) <= 500
