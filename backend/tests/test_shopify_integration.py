"""Tests for ShopifyIntegration — connect, sync, status, and _record_sync_failure.

Mirrors test_whoop_sync.py's style: direct provider instantiation with
monkeypatched collaborators, no HTTP server.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal.shopify import ShopifyIntegration

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


# The shop_metadata_config writer moved to services/shopify/state.py, which
# now owns both directions of the Integration.config shape; its tests live in
# test_shopify_state.py alongside the readers.


# ── description / sync() alignment ───────────────────────────────────────────


def test_description_does_not_overclaim_live_data_without_dashboard_context():
    """REQ-SHOP-001/002 regression guard.

    sync() is a metadata-only refresh (rows_written == 0 by design — see
    test_sync_updates_config_and_returns_zero_rows_written); it never
    ingests orders, revenue, or inventory. If the UI-facing description
    claims all three, it must also say where that live data actually comes
    from (GET /api/v1/shopify/dashboard), so a reader isn't misled into
    thinking sync() populates it.

    This intentionally does not pin an exact string — only the invariant
    that "orders + revenue + inventory" claims must be paired with a
    "dashboard" pointer. A future copy edit is free to reword either side
    as long as the pairing holds.
    """
    provider = ShopifyIntegration()
    desc = provider.description.lower()

    claims_live_orders_revenue_inventory = (
        "orders" in desc and "revenue" in desc and "inventory" in desc
    )

    assert not claims_live_orders_revenue_inventory or "dashboard" in desc, (
        "ShopifyIntegration.description promises live orders/revenue/inventory "
        f"but never mentions 'dashboard' to clarify that sync() (rows_written=0) "
        f"is NOT the source. Got: {provider.description!r}. Fix by either (a) "
        "adding '...from your Shopify store dashboard' so the description "
        "points at GET /api/v1/shopify/dashboard, the actual live-read source, "
        "or (b) implementing real order/revenue/inventory ingestion in sync() "
        "so the claim is true of sync() itself."
    )


# ── connect ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_raises_when_no_user():
    provider = ShopifyIntegration()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(
            user=None, db=MagicMock(), payload={"shop": "test.myshopify.com"}
        )

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
        await provider.connect(
            user=user, db=MagicMock(), payload={"shop": "not-a-shopify-domain"}
        )


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

    import src.services.shopify.cache as shopify_cache_mod
    import src.services.shopify.client as shopify_client_mod

    monkeypatch.setattr(
        shopify_client_mod,
        "fetch_shop_metadata",
        AsyncMock(
            return_value={"ianaTimezone": "UTC", "currencyCode": "USD", "name": "Test"}
        ),
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

    import src.services.shopify.cache as shopify_cache_mod
    import src.services.shopify.client as shopify_client_mod

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
    integration = _make_integration(config={"shop_domain": "best-store.myshopify.com"})
    db = _make_db()

    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    import src.services.shopify.cache as shopify_cache_mod
    import src.services.shopify.client as shopify_client_mod

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


# ── SEC: sync-failure detail must not leak request URLs / credentials ────────


@pytest.mark.asyncio
async def test_record_sync_failure_does_not_persist_or_echo_request_url():
    """SEC-001 regression (see tests/test_integration_error_leakage.py):
    integration.last_error is returned verbatim by GET /{slug}/status and the
    raised message becomes the 400 body of POST /{slug}/sync. httpx puts the
    full request URL — including any query-string credential — in the message
    of every HTTPStatusError, so both must carry safe_detail(exc) only.
    """
    import httpx

    integration = _make_integration()
    db = _make_db()
    leaky_url = "https://store.myshopify.com/admin/api/graphql.json?token=zzSECRETzz"
    request = httpx.Request("POST", leaky_url)
    exc = httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(401, request=request)
    )

    with pytest.raises(IntegrationError) as exc_info:
        await ShopifyIntegration._record_sync_failure(integration, exc, db)

    assert "zzSECRETzz" not in exc_info.value.message
    assert "zzSECRETzz" not in integration.last_error
    assert "401" in integration.last_error
