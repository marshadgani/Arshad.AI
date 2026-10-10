"""Failure-path regressions for the FEAT-125 Shopify intelligence routes.

A failed or unknown lookup must never read as a valid discount or as "no
unanswered threads", and degraded responses must not be cached.
"""
# ruff: noqa: F811

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from src.api.v1 import shopify as shopify_module
from src.services.shopify import providers
from src.services.shopify.discount import evaluate_discount
from src.tools.base import ProviderNotLinked
from test_shopify_intelligence import (  # noqa: F401
    THROTTLED,
    VID,
    _discount,
    _FakeIntegration,
    _integration,
    _patch_cover,
    _patch_debt,
    client,
)

URL = "/api/v1/shopify/discount-simulator"
BODY = {"variant_id": VID, "discount_percent": 10}


def _post(client):
    return client.post(URL, json=BODY).json()["data"]


def test_discount_expired_integration_needs_reauth_without_fetching(
    client, monkeypatch
):
    _integration(monkeypatch, _FakeIntegration("expired"))
    fetch = AsyncMock(side_effect=AssertionError("must not fetch"))
    monkeypatch.setattr(shopify_module, "_execute_discount_query", fetch)

    d = _post(client)

    assert d["needs_reauth"] is True
    assert d["valid"] is None


def test_discount_throttled_is_unknown_not_valid(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _discount(monkeypatch, {"variant": None, "partial_failures": [], "throttled": True})

    d = _post(client)

    assert d["partial_failures"] == ["throttled"]
    assert d["valid"] is None


def test_discount_shopify_http_error_is_unknown_not_valid(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    monkeypatch.setattr(
        shopify_module,
        "_execute_discount_query",
        AsyncMock(side_effect=httpx.ConnectError("x")),
    )

    d = _post(client)

    assert d["partial_failures"] == ["variant"]
    assert d["valid"] is None


def test_discount_graphql_error_with_null_variant_is_a_failure(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _discount(
        monkeypatch,
        {"variant": None, "partial_failures": ["variants"], "throttled": False},
    )

    d = _post(client)

    assert d["partial_failures"] == ["variants"]
    assert d["variant_found"] is True
    assert d["valid"] is None


def test_discount_malformed_price_is_unknown_not_valid(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _discount(
        monkeypatch,
        {
            "variant": {"price": "n/a", "inventoryItem": {"unitCost": None}},
            "partial_failures": [],
            "throttled": False,
        },
    )

    d = _post(client)

    assert d["partial_failures"] == ["variant"]
    assert d["valid"] is None


@pytest.mark.parametrize(
    ("price", "cost"),
    [("3.00", "1.00"), ("10.00", "3.33"), ("19.99", "7.77"), ("50.00", "40.00")],
)
def test_safe_maximum_discount_never_lands_below_cost(price, cost):
    first = evaluate_discount(Decimal(price), Decimal(cost), 99)
    assert first.valid is False

    suggested = float(first.max_safe_discount_pct)
    again = evaluate_discount(Decimal(price), Decimal(cost), suggested)

    assert again.valid is True


def test_debt_degraded_orders_response_is_not_cached(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_debt(monkeypatch)
    monkeypatch.setattr(
        shopify_module,
        "_execute_orders_query",
        AsyncMock(side_effect=httpx.ConnectError("x")),
    )

    client.get("/api/v1/shopify/service-debt")

    shopify_module._set_cached_intel.assert_not_awaited()


def test_debt_throttled_orders_are_flagged_and_not_cached(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_debt(monkeypatch, orders=THROTTLED)

    d = client.get("/api/v1/shopify/service-debt").json()["data"]

    assert "throttled" in d["partial_failures"]
    shopify_module._set_cached_intel.assert_not_awaited()


def test_debt_gmail_not_connected_is_not_cached(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_debt(monkeypatch, gmail=ProviderNotLinked("google"))

    client.get("/api/v1/shopify/service-debt")

    shopify_module._set_cached_intel.assert_not_awaited()


def test_cover_calendar_not_connected_is_not_cached(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, calendar=ProviderNotLinked("google"))

    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]

    assert d["calendar_connected"] is False
    shopify_module._set_cached_intel.assert_not_awaited()


@pytest.mark.parametrize("bad", [ValueError("bad json"), KeyError("access_token")])
def test_malformed_google_reply_is_a_partial_failure_not_a_500(bad):
    assert providers.parse_gmail_result(bad).partial_failures == ["gmail"]
    assert providers.parse_calendar_result(bad).partial_failures == ["calendar"]


def test_customer_name_with_extra_spaces_still_matches():
    from src.services.shopify.service_debt import match_threads_to_orders

    orders = [
        {
            "id": "o1",
            "name": "#5",
            "customer": {"displayName": "John  Doe"},
        }
    ]
    threads = match_threads_to_orders(
        [{"id": "t", "snippet": "hi from John Doe"}], orders
    )

    assert threads[0].matched_order_id == "o1"


def test_duplicate_customer_names_match_the_first_order():
    from src.services.shopify.service_debt import match_threads_to_orders

    orders = [
        {"id": "o1", "name": "#1001", "customer": {"displayName": "Jane Smith"}},
        {"id": "o2", "name": "#1002", "customer": {"displayName": "jane smith"}},
    ]
    threads = match_threads_to_orders(
        [{"id": "t", "snippet": "Hello from Jane Smith"}], orders
    )

    assert threads[0].matched_order_id == "o1"
    assert threads[0].match_confidence == "low"


@pytest.mark.asyncio
async def test_google_list_calls_send_a_fields_mask(monkeypatch):
    calendar = AsyncMock(return_value={"items": []})
    gmail = AsyncMock(return_value={"threads": []})
    from src.tools.clients import gmail as gmail_client
    from src.tools.clients import google_calendar as calendar_client

    monkeypatch.setattr(calendar_client, "request", calendar)
    monkeypatch.setattr(gmail_client, "request", gmail)

    await providers.list_calendar_events(
        None, object(), "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"
    )
    await providers.list_gmail_threads(None, object())

    assert "nextPageToken" in calendar.await_args.kwargs["params"]["fields"]
    assert gmail.await_args.kwargs["params"]["fields"] == (
        "nextPageToken,threads(id,snippet)"
    )
