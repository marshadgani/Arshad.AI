"""FEAT-125 Shopify intelligence layer: pure services + the three routes."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from src.api.v1 import shopify as shopify_module
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.services.shopify import client as shopify_client
from src.services.shopify.discount import evaluate_discount, parse_variant_pricing
from src.services.shopify.inventory_cover import build_inventory_cover, travel_windows
from src.services.shopify.service_debt import match_threads_to_orders, rank_threads
from src.tools.base import ProviderNotLinked, ProviderReauthRequired, ToolError

AS_OF = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
VID = "gid://shopify/ProductVariant/1"


# ── discount ──────────────────────────────────────────────────────────────


def test_discount_valid_when_margin_positive():
    r = evaluate_discount(Decimal("50.00"), Decimal("30.00"), 20)
    assert r.valid is True
    assert r.margin_remaining == "10.00"
    assert r.discounted_price == "40.00"


def test_discount_exactly_break_even_is_valid():
    r = evaluate_discount(Decimal("50.00"), Decimal("40.00"), 20)
    assert r.valid is True
    assert r.margin_remaining == "0.00"


def test_discount_below_cost_rejected_with_safe_maximum():
    r = evaluate_discount(Decimal("50.00"), Decimal("40.00"), 30)
    assert r.valid is False
    assert r.max_safe_discount_pct == "20.00"
    assert "cannot break even" in r.reason
    # the suggestion itself must be valid
    assert evaluate_discount(Decimal("50.00"), Decimal("40.00"), 20).valid is True


def test_discount_unknown_cost_is_neither_true_nor_false():
    r = evaluate_discount(Decimal("50.00"), None, 10)
    assert r.valid is None
    assert r.cost_unavailable is True


def test_discount_100_percent_rejected_when_cost_positive():
    assert evaluate_discount(Decimal("10"), Decimal("1"), 100).valid is False


def test_parse_variant_pricing_handles_missing_and_malformed():
    assert parse_variant_pricing({"price": "9.99"}) == (Decimal("9.99"), None)
    assert parse_variant_pricing(
        {"price": "9.99", "inventoryItem": {"unitCost": {"amount": "4.5"}}}
    ) == (Decimal("9.99"), Decimal("4.5"))
    assert parse_variant_pricing({"price": "abc"}) == (None, None)
    assert parse_variant_pricing({}) == (None, None)


# ── inventory cover ───────────────────────────────────────────────────────


def _variant(vid, available, tracked=True):
    return {
        "id": vid,
        "inventoryItem": {
            "tracked": tracked,
            "inventoryLevels": {
                "edges": [
                    {
                        "node": {
                            "quantities": [{"name": "available", "quantity": available}]
                        }
                    }
                ]
            },
        },
    }


def _order(vid, qty):
    return {
        "lineItems": {"edges": [{"node": {"quantity": qty, "variant": {"id": vid}}}]}
    }


def _event(start, end, title="Trip"):
    return {"summary": title, "start": {"date": start}, "end": {"date": end}}


def _build(variants, orders, events, **kw):
    args = dict(
        as_of=AS_OF,
        window_days=30,
        calendar_connected=True,
        calendar_needs_reauth=False,
        partial_failures=[],
    )
    args.update(kw)
    return build_inventory_cover(
        {"variants": variants} if variants is not None else None,
        {"orders": orders} if orders is not None else None,
        events,
        **args,
    )


def test_cover_is_available_over_daily_velocity():
    r = _build([_variant(VID, 30)], [_order(VID, 30)], [])
    item = r.days_of_cover[0]
    assert item.velocity_30d == "1.0"
    assert item.days_of_cover == "30.0"
    assert item.is_alert is False


def test_zero_sales_has_no_cover_and_never_alerts():
    r = _build([_variant(VID, 5)], [], [_event("2026-10-09", "2026-10-20")])
    item = r.days_of_cover[0]
    assert item.no_recent_sales is True
    assert item.days_of_cover is None
    assert r.alerts == []


def test_unknown_orders_do_not_masquerade_as_no_sales():
    r = _build([_variant(VID, 5)], None, [])
    item = r.days_of_cover[0]
    assert item.no_recent_sales is False
    assert item.days_of_cover is None


def test_stockout_inside_travel_window_alerts():
    # 10 units, 1/day -> stockout 2026-10-19, inside Oct 15 - Oct 22.
    r = _build(
        [_variant(VID, 10)], [_order(VID, 30)], [_event("2026-10-15", "2026-10-22")]
    )
    assert r.alerts[0].projected_stockout_date == "2026-10-19"
    assert r.alerts[0].travel_event_title == "Trip"
    assert r.days_of_cover[0].is_alert is True


def test_window_end_is_exclusive():
    # stockout 2026-10-19; event covers Oct 15-18 (end.date Oct 19 exclusive).
    r = _build(
        [_variant(VID, 10)], [_order(VID, 30)], [_event("2026-10-15", "2026-10-19")]
    )
    assert r.alerts == []


def test_single_day_and_timed_events_are_not_travel_windows():
    events = [
        _event("2026-10-19", "2026-10-20"),
        {
            "start": {"dateTime": "2026-10-15T09:00:00Z"},
            "end": {"dateTime": "2026-10-25T09:00:00Z"},
        },
        {**_event("2026-10-15", "2026-10-22"), "status": "cancelled"},
        _event("garbage", "2026-10-22"),
    ]
    assert travel_windows(events) == []
    assert _build([_variant(VID, 10)], [_order(VID, 30)], events).alerts == []


def test_two_day_event_counts_as_travel():
    assert len(travel_windows([_event("2026-10-19", "2026-10-21")])) == 1


def test_calendar_not_connected_skips_escalation():
    r = _build(
        [_variant(VID, 10)],
        [_order(VID, 30)],
        [_event("2026-10-15", "2026-10-22")],
        calendar_connected=False,
    )
    assert r.alerts == []
    assert r.calendar_connected is False


def test_untracked_and_levelless_variants_skipped():
    levelless = {
        "id": "x",
        "inventoryItem": {"tracked": True, "inventoryLevels": {"edges": []}},
    }
    r = _build([_variant("a", 1, tracked=False), levelless], [], [])
    assert r.days_of_cover == []


def test_truncation_flags_propagate():
    r = build_inventory_cover(
        {"variants": [], "variants_has_next_page": True},
        {"orders": [], "orders_has_next_page": False, "line_items_truncated": True},
        [],
        as_of=AS_OF,
        window_days=30,
        calendar_connected=True,
        calendar_needs_reauth=False,
        partial_failures=[],
    )
    assert r.variants_truncated is True
    assert r.orders_truncated is True


# ── service debt matching ─────────────────────────────────────────────────

ORDERS = [
    {
        "id": "gid://shopify/Order/9",
        "name": "#1042",
        "customer": {"displayName": "Jane Smith"},
    },
    {
        "id": "gid://shopify/Order/8",
        "name": "#1041",
        "customer": {"displayName": "Sam"},
    },
]


def _thread(snippet, tid="t1"):
    return {"id": tid, "snippet": snippet, "historyId": "1"}


def test_hash_reference_is_high_confidence():
    [m] = match_threads_to_orders([_thread("Where is order #1042?")], ORDERS)
    assert (m.matched_order_name, m.match_confidence) == ("#1042", "high")


def test_word_reference_and_full_name_are_low_confidence():
    a, b = match_threads_to_orders(
        [_thread("my order 1041 is late"), _thread("Regards, jane smith")], ORDERS
    )
    assert (a.matched_order_id, a.match_confidence) == ("gid://shopify/Order/8", "low")
    assert (b.matched_order_name, b.match_confidence) == ("#1042", "low")


def test_single_word_names_and_unknown_numbers_do_not_match():
    [m] = match_threads_to_orders([_thread("Hi, Sam here about #9999")], ORDERS)
    assert m.matched_order_id is None and m.match_confidence is None


def test_html_entities_decoded_before_matching_and_storage():
    [m] = match_threads_to_orders(
        [_thread("Jane Smith &amp; co: it&#39;s late")], ORDERS
    )
    assert m.snippet == "Jane Smith & co: it's late"
    assert m.matched_order_name == "#1042"


def test_rank_reverses_newest_first_input():
    ts = match_threads_to_orders([_thread("a", "new"), _thread("b", "old")], [])
    assert [t.id for t in rank_threads(ts)] == ["old", "new"]


# ── client ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orders_query_passes_anchor_and_reports_truncation(monkeypatch):
    seen = {}

    async def fake_post(url, headers, query, variables, shop, *, max_retries):
        seen.update(variables=variables, max_retries=max_retries)
        return {
            "data": {
                "orders": {
                    "pageInfo": {"hasNextPage": True},
                    "edges": [
                        {
                            "node": {
                                "id": "o",
                                "lineItems": {
                                    "pageInfo": {"hasNextPage": True},
                                    "edges": [],
                                },
                            }
                        }
                    ],
                }
            }
        }

    monkeypatch.setattr(shopify_client, "_post_with_retry", fake_post)
    out = await shopify_client.execute_orders_query(
        "s.myshopify.com", "t", "2026-09-09T00:00:00Z", max_retries=0
    )
    assert "2026-09-09T00:00:00Z" in seen["variables"]["ordersQuery"]
    assert seen["max_retries"] == 0
    assert out["orders_has_next_page"] is True
    assert out["line_items_truncated"] is True
    assert out["throttled"] is False


@pytest.mark.asyncio
async def test_throttled_body_is_surfaced(monkeypatch):
    body = {"errors": [{"message": "t", "extensions": {"code": "THROTTLED"}}]}
    monkeypatch.setattr(
        shopify_client, "_post_with_retry", AsyncMock(return_value=body)
    )
    out = await shopify_client.execute_variant_inventory_query("s.myshopify.com", "t")
    assert out["throttled"] is True
    assert out["variants"] == []


@pytest.mark.asyncio
async def test_post_with_retry_zero_retries_makes_one_attempt(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(
            200, json={"errors": [{"extensions": {"code": "THROTTLED"}}]}
        )

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        shopify_client.httpx,
        "AsyncClient",
        lambda **kw: real(transport=transport, **kw),
    )
    await shopify_client._post_with_retry(
        "https://x/graphql.json", {}, "q", {}, "x", max_retries=0
    )
    assert len(calls) == 1


# ── routes ────────────────────────────────────────────────────────────────


class _FakeUser:
    id = uuid.uuid4()


class _FakeIntegration:
    def __init__(self, status="connected"):
        self.id = uuid.uuid4()
        self.status = status
        self.last_error = None
        self.config = {"shop_domain": "my-store.myshopify.com"}


@pytest.fixture
def client(monkeypatch):
    async def _user():
        return _FakeUser()

    async def _db():
        db = MagicMock()
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    m = monkeypatch.setattr
    m(shopify_module, "_check_rate_limit", AsyncMock())
    m(shopify_module, "_get_cached_intel", AsyncMock(return_value=None))
    m(shopify_module, "_set_cached_intel", AsyncMock())
    m(shopify_module, "_get_token", AsyncMock(return_value="tok"))
    m(shopify_module, "_mark_healthy", AsyncMock())
    m(shopify_module, "_apply_error_status", AsyncMock())
    yield TestClient(app)
    app.dependency_overrides.clear()


def _integration(monkeypatch, integ):
    monkeypatch.setattr(
        shopify_module, "_find_integration", AsyncMock(return_value=integ)
    )


VARIANTS = {
    "variants": [_variant(VID, 10)],
    "variants_has_next_page": False,
    "partial_failures": [],
    "throttled": False,
}
ORDERS_OK = {
    "orders": [_order(VID, 30)],
    "orders_has_next_page": False,
    "line_items_truncated": False,
    "partial_failures": [],
    "throttled": False,
}
THROTTLED = {"variants": [], "orders": [], "partial_failures": [], "throttled": True}


def _patch_cover(monkeypatch, variants=VARIANTS, orders=ORDERS_OK, calendar=None):
    monkeypatch.setattr(
        shopify_module,
        "_execute_variants_query",
        variants if callable(variants) else AsyncMock(return_value=variants),
    )
    monkeypatch.setattr(
        shopify_module,
        "_execute_orders_query",
        orders if callable(orders) else AsyncMock(return_value=orders),
    )
    cal = calendar if calendar is not None else {"items": []}
    monkeypatch.setattr(
        shopify_module,
        "_list_calendar_events",
        AsyncMock(side_effect=cal)
        if isinstance(cal, BaseException)
        else AsyncMock(return_value=cal),
    )


def test_cover_not_connected(client, monkeypatch):
    _integration(monkeypatch, None)
    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]
    assert d["connected"] is False


def test_cover_expired_reports_reauth_without_fetching(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration("expired"))
    _patch_cover(monkeypatch, variants=AsyncMock(side_effect=AssertionError))
    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]
    assert d["needs_reauth"] is True


def test_cover_passes_date_anchor_to_orders_seam(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    orders = AsyncMock(return_value=ORDERS_OK)
    _patch_cover(monkeypatch, orders=orders)
    client.get("/api/v1/shopify/inventory-cover")
    since = orders.await_args.args[2]
    assert since.endswith("Z") and "T" in since


def test_cover_happy_path_with_alert(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    today = datetime.now(timezone.utc).date()
    from datetime import timedelta

    start = (today + timedelta(days=1)).isoformat()
    end = (today + timedelta(days=60)).isoformat()
    _patch_cover(monkeypatch, calendar={"items": [_event(start, end)]})
    r = client.get("/api/v1/shopify/inventory-cover")
    d = r.json()["data"]
    assert r.status_code == 200
    assert d["calendar_connected"] is True
    assert len(d["alerts"]) == 1


def test_cover_calendar_not_linked_vs_reauth(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, calendar=ProviderNotLinked("google"))
    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]
    assert d["calendar_connected"] is False
    assert d["partial_failures"] == []

    _patch_cover(monkeypatch, calendar=ProviderReauthRequired("google"))
    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]
    assert d["calendar_connected"] is True
    assert d["calendar_needs_reauth"] is True
    assert d["needs_reauth"] is False
    assert "calendar" in d["partial_failures"]


def test_cover_generic_calendar_error_is_partial_failure_not_500(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, calendar=ToolError("provider_http_error", "boom"))
    r = client.get("/api/v1/shopify/inventory-cover")
    assert r.status_code == 200
    assert r.json()["data"]["partial_failures"] == ["calendar"]


def test_cover_throttled_query_is_rerun_serially_without_retries(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    calls = []

    async def orders(shop, token, since, **kw):
        calls.append(kw.get("max_retries"))
        return THROTTLED if len(calls) == 1 else ORDERS_OK

    _patch_cover(monkeypatch, orders=orders)
    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]
    assert calls == [None, 0]
    assert d["partial_failures"] == []
    assert d["days_of_cover"][0]["days_of_cover"] == "10.0"


def test_cover_still_throttled_degrades_honestly(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, orders=AsyncMock(return_value=THROTTLED))
    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]
    assert d["partial_failures"] == ["throttled"]
    item = d["days_of_cover"][0]
    assert item["no_recent_sales"] is False and item["days_of_cover"] is None


def test_cover_shopify_http_error_is_partial_failure(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, variants=AsyncMock(side_effect=httpx.ConnectError("x")))
    r = client.get("/api/v1/shopify/inventory-cover")
    assert r.status_code == 200
    assert "variants" in r.json()["data"]["partial_failures"]


def test_cover_unexpected_error_is_not_swallowed(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, variants=AsyncMock(side_effect=KeyError("bug")))
    with pytest.raises(KeyError):
        client.get("/api/v1/shopify/inventory-cover")


# discount route


def _discount(monkeypatch, result):
    monkeypatch.setattr(
        shopify_module, "_execute_discount_query", AsyncMock(return_value=result)
    )


def test_discount_rejects_bad_variant_id_and_range(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    for body in (
        {"variant_id": "x\nINJECT", "discount_percent": 10},
        {"variant_id": VID, "discount_percent": 101},
        {"variant_id": VID, "discount_percent": -1},
        {"variant_id": "a" * 101, "discount_percent": 1},
    ):
        assert (
            client.post("/api/v1/shopify/discount-simulator", json=body).status_code
            == 422
        )


def test_discount_route_valid_invalid_and_unknown_cost(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    with_cost = {
        "variant": {
            "price": "50.00",
            "inventoryItem": {"unitCost": {"amount": "40.00"}},
        },
        "partial_failures": [],
        "throttled": False,
    }
    _discount(monkeypatch, with_cost)
    post = lambda pct: client.post(  # noqa: E731
        "/api/v1/shopify/discount-simulator",
        json={"variant_id": VID, "discount_percent": pct},
    ).json()["data"]
    assert post(10)["valid"] is True
    assert post(30)["valid"] is False

    _discount(
        monkeypatch,
        {
            "variant": {"price": "50.00", "inventoryItem": {"unitCost": None}},
            "partial_failures": [],
            "throttled": False,
        },
    )
    d = post(10)
    assert d["valid"] is None and d["cost_unavailable"] is True


def test_discount_route_unknown_variant_and_not_connected(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _discount(
        monkeypatch, {"variant": None, "partial_failures": [], "throttled": False}
    )
    d = client.post(
        "/api/v1/shopify/discount-simulator",
        json={"variant_id": VID, "discount_percent": 5},
    ).json()["data"]
    assert d["variant_found"] is False and d["valid"] is None

    _integration(monkeypatch, None)
    d = client.post(
        "/api/v1/shopify/discount-simulator",
        json={"variant_id": VID, "discount_percent": 5},
    ).json()["data"]
    assert d["connected"] is False


# service debt route

GMAIL_OK = {"threads": [_thread("Where is #1042?", "a"), _thread("hello", "b")]}


def _patch_debt(monkeypatch, gmail=GMAIL_OK, orders=None):
    monkeypatch.setattr(
        shopify_module,
        "_list_gmail_threads",
        AsyncMock(side_effect=gmail)
        if isinstance(gmail, BaseException)
        else AsyncMock(return_value=gmail),
    )
    monkeypatch.setattr(
        shopify_module,
        "_execute_orders_query",
        AsyncMock(
            return_value=orders
            or {
                "orders": ORDERS,
                "orders_has_next_page": False,
                "partial_failures": [],
                "throttled": False,
            }
        ),
    )


def test_debt_matches_and_ranks_oldest_first(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_debt(monkeypatch)
    d = client.get("/api/v1/shopify/service-debt").json()["data"]
    assert [t["id"] for t in d["threads"]] == ["b", "a"]
    assert d["threads"][1]["match_confidence"] == "high"
    assert d["threads_truncated"] is False


def test_debt_next_page_token_sets_truncated(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_debt(monkeypatch, gmail={**GMAIL_OK, "nextPageToken": "n"})
    assert (
        client.get("/api/v1/shopify/service-debt").json()["data"]["threads_truncated"]
        is True
    )


def test_debt_gmail_not_linked_and_reauth(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_debt(monkeypatch, gmail=ProviderNotLinked("google"))
    d = client.get("/api/v1/shopify/service-debt").json()["data"]
    assert d["gmail_connected"] is False and d["threads"] == []

    _patch_debt(monkeypatch, gmail=ProviderReauthRequired("google"))
    d = client.get("/api/v1/shopify/service-debt").json()["data"]
    assert d["gmail_connected"] is True and d["needs_reauth"] is True
    assert d["partial_failures"] == ["gmail"]


def test_debt_without_shopify_still_lists_threads(client, monkeypatch):
    _integration(monkeypatch, None)
    _patch_debt(monkeypatch)
    orders = AsyncMock(side_effect=AssertionError("no shopify"))
    monkeypatch.setattr(shopify_module, "_execute_orders_query", orders)
    d = client.get("/api/v1/shopify/service-debt").json()["data"]
    assert d["shopify_connected"] is False
    assert len(d["threads"]) == 2
    assert all(t["match_confidence"] is None for t in d["threads"])


def test_debt_orders_failure_keeps_threads(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_debt(monkeypatch)
    monkeypatch.setattr(
        shopify_module,
        "_execute_orders_query",
        AsyncMock(side_effect=httpx.ConnectError("x")),
    )
    d = client.get("/api/v1/shopify/service-debt").json()["data"]
    assert len(d["threads"]) == 2
    assert d["partial_failures"] == ["orders"]


def test_debt_cache_hit_short_circuits(client, monkeypatch):
    monkeypatch.setattr(
        shopify_module,
        "_get_cached_intel",
        AsyncMock(return_value={"gmail_connected": True, "cached_at": "x"}),
    )
    monkeypatch.setattr(
        shopify_module, "_list_gmail_threads", AsyncMock(side_effect=AssertionError)
    )
    assert client.get("/api/v1/shopify/service-debt").json()["data"]["cached_at"] == "x"


# ── silent-failure regressions ────────────────────────────────────────────


def test_cover_failed_orders_root_field_is_unknown_velocity_not_no_sales(
    client, monkeypatch
):
    _integration(monkeypatch, _FakeIntegration())
    denied = {**ORDERS_OK, "orders": [], "partial_failures": ["orders"]}
    _patch_cover(monkeypatch, orders=AsyncMock(return_value=denied))
    d = client.get("/api/v1/shopify/inventory-cover").json()["data"]
    assert "orders" in d["partial_failures"]
    item = d["days_of_cover"][0]
    assert item["no_recent_sales"] is False and item["days_of_cover"] is None


def test_cover_degraded_response_is_not_cached(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, orders=AsyncMock(return_value=THROTTLED))
    client.get("/api/v1/shopify/inventory-cover")
    shopify_module._set_cached_intel.assert_not_awaited()


def test_cover_clean_response_is_cached(client, monkeypatch):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch)
    client.get("/api/v1/shopify/inventory-cover")
    shopify_module._set_cached_intel.assert_awaited_once()


def test_cover_fetch_failure_is_logged(client, monkeypatch, caplog):
    _integration(monkeypatch, _FakeIntegration())
    _patch_cover(monkeypatch, variants=AsyncMock(side_effect=httpx.ConnectError("x")))
    with caplog.at_level("WARNING"):
        client.get("/api/v1/shopify/inventory-cover")
    assert any("variants fetch failed" in r.getMessage() for r in caplog.records)
