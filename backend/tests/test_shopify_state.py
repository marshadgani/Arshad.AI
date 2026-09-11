"""Tests for src/services/shopify/state.py and src/services/shopify/parsers.py.

Covers:
  - shop_domain / shop_context / shop_presentation accessors
  - day_window timestamp format (bare-Z suffix, not +00:00)
  - find_integration delegation
  - tokens.get_access_token delegation
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.integrations.base import IntegrationError
from src.services.shopify import state as shopify_state
from src.services.shopify import tokens as shopify_tokens
from src.services.shopify.parsers import day_window


# ── Helper ────────────────────────────────────────────────────────────────────


def _make_integration(config: dict | None = None, status: str = "connected"):
    integration = MagicMock()
    integration.id = uuid.uuid4()
    integration.status = status
    integration.config = config or {}
    return integration


# ── shop_domain ───────────────────────────────────────────────────────────────


def test_shop_domain_returns_stored_domain():
    integration = _make_integration(config={"shop_domain": "store.myshopify.com"})

    result = shopify_state.shop_domain(integration)

    assert result == "store.myshopify.com"


def test_shop_domain_raises_integration_error_when_missing():
    integration = _make_integration(config={})

    with pytest.raises(IntegrationError) as exc_info:
        shopify_state.shop_domain(integration)

    assert exc_info.value.code == "shopify_shop_missing"


def test_shop_domain_raises_integration_error_when_config_is_none():
    integration = _make_integration(config=None)

    with pytest.raises(IntegrationError) as exc_info:
        shopify_state.shop_domain(integration)

    assert exc_info.value.code == "shopify_shop_missing"


# ── shop_presentation ─────────────────────────────────────────────────────────


def test_shop_presentation_returns_stored_fields():
    integration = _make_integration(
        config={
            "shop_name": "My Store",
            "currency_code": "GBP",
            "shop_timezone": "Europe/London",
        }
    )

    result = shopify_state.shop_presentation(integration)

    assert result.shop_name == "My Store"
    assert result.currency_code == "GBP"
    assert result.timezone == "Europe/London"


def test_shop_presentation_returns_none_fields_for_empty_config():
    integration = _make_integration(config={})

    result = shopify_state.shop_presentation(integration)

    assert result.shop_name is None
    assert result.currency_code is None
    assert result.timezone is None


def test_shop_presentation_never_raises_even_with_no_config():
    integration = _make_integration(config=None)

    # Must not raise — it is the safe path used for degraded responses
    result = shopify_state.shop_presentation(integration)

    assert result.shop_name is None


# ── shop_context ──────────────────────────────────────────────────────────────


def test_shop_context_returns_correct_fields():
    integration = _make_integration(
        config={
            "shop_domain": "store.myshopify.com",
            "shop_timezone": "America/New_York",
            "currency_code": "USD",
            "shop_name": "Test Store",
        }
    )

    ctx = shopify_state.shop_context(integration)

    assert ctx.shop == "store.myshopify.com"
    assert ctx.timezone == "America/New_York"
    assert ctx.currency_code == "USD"
    assert ctx.shop_name == "Test Store"


def test_shop_context_defaults_timezone_and_currency_when_absent():
    integration = _make_integration(config={"shop_domain": "store.myshopify.com"})

    ctx = shopify_state.shop_context(integration)

    assert ctx.timezone == "UTC"
    assert ctx.currency_code == "USD"


def test_shop_context_raises_when_shop_domain_missing():
    integration = _make_integration(config={"shop_timezone": "UTC"})

    with pytest.raises(IntegrationError) as exc_info:
        shopify_state.shop_context(integration)

    assert exc_info.value.code == "shopify_shop_missing"


# ── day_window timestamp format ───────────────────────────────────────────────


def test_day_window_returns_bare_z_suffix_not_plus_00_offset():
    """Regression: Shopify's search grammar wants '2026-09-11T00:00:00Z', not
    '2026-09-11T00:00:00+00:00'. A '+00:00' suffix risks mis-parsing the
    ':00' as a second field delimiter in `created_at:>=…` queries.
    """
    now = datetime(2026, 9, 11, 15, 30, 0, tzinfo=timezone.utc)

    day_start, day_end = day_window("UTC", now)

    assert day_start.endswith("Z")
    assert day_end.endswith("Z")
    assert "+" not in day_start
    assert "+" not in day_end


def test_day_window_start_is_midnight_utc_for_utc_shop():
    now = datetime(2026, 9, 11, 15, 30, 45, tzinfo=timezone.utc)

    day_start, _ = day_window("UTC", now)

    assert day_start == "2026-09-11T00:00:00Z"


def test_day_window_end_matches_current_time_for_utc_shop():
    now = datetime(2026, 9, 11, 15, 30, 45, tzinfo=timezone.utc)

    _, day_end = day_window("UTC", now)

    assert day_end == "2026-09-11T15:30:45Z"


def test_day_window_falls_back_to_utc_for_unknown_timezone():
    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

    # Must not raise — bad stored timezone degrades to UTC
    day_start, day_end = day_window("Not/A/Timezone", now)

    assert day_start == "2026-09-11T00:00:00Z"
    assert day_end.endswith("Z")


def test_day_window_accounts_for_non_utc_timezone():
    """America/New_York is UTC-4 in summer. Midnight NYC = 04:00 UTC."""
    now = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)  # 06:00 NYC

    day_start, _ = day_window("America/New_York", now)

    # Midnight NYC on 2026-09-11 is 04:00 UTC
    assert day_start == "2026-09-11T04:00:00Z"


# ── find_integration ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_integration_delegates_to_shared_state(monkeypatch):
    from src.services.shopify import state as shopify_state_mod

    mock_result = MagicMock()
    shared_find = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("src.services.integrations.state.find_integration", shared_find)

    db = MagicMock()
    result = await shopify_state_mod.find_integration("user-123", db)

    shared_find.assert_awaited_once_with("user-123", "shopify", db)
    assert result is mock_result


# ── classify_error ────────────────────────────────────────────────────────────


def test_classify_error_reauth_code_returns_needs_reauth_true():
    exc = IntegrationError("refresh_failed", "token gone")

    needs_reauth, _ = shopify_state.classify_error(exc)

    assert needs_reauth is True


def test_classify_error_shopify_shop_missing_returns_needs_reauth_true():
    exc = IntegrationError("shopify_shop_missing", "no domain stored")

    needs_reauth, _ = shopify_state.classify_error(exc)

    assert needs_reauth is True


def test_classify_error_generic_exception_returns_needs_reauth_false():
    import httpx
    exc = httpx.ConnectTimeout("timed out")

    needs_reauth, _ = shopify_state.classify_error(exc)

    assert needs_reauth is False


# ── tokens.get_access_token ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_access_token_delegates_to_shopify_integration(monkeypatch):
    import src.integrations.personal.shopify as shopify_integration_mod

    mock_token = "test-token-xyz"
    mock_instance = MagicMock()
    mock_instance.get_access_token = AsyncMock(return_value=mock_token)
    monkeypatch.setattr(
        shopify_integration_mod, "ShopifyIntegration", lambda: mock_instance
    )

    integration = _make_integration(config={"shop_domain": "store.myshopify.com"})
    db = MagicMock()

    result = await shopify_tokens.get_access_token(integration, db)

    assert result == mock_token
    mock_instance.get_access_token.assert_awaited_once_with(
        integration=integration, db=db
    )
