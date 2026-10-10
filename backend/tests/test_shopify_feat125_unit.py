"""Pure-function edge-case tests for FEAT-125 schemas, parsers, and matchers.

These complement test_shopify_intelligence.py (which covers the main paths)
with boundary and adversarial cases the test plan's gap list calls out.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from src.schemas.shopify import DiscountSimulatorRequest, ThreadMeta
from src.services.shopify.discount import evaluate_discount, parse_variant_pricing
from src.services.shopify.inventory_cover import travel_windows
from src.services.shopify.service_debt import match_threads_to_orders, rank_threads

# ── REQ-006 / variant_id Field constraint ──────────────────────────────────
# acceptance: pattern r'^[a-zA-Z0-9_/:-]{1,100}$', 422 on mismatch

VALID_IDS = [
    "gid://shopify/ProductVariant/123",
    "a",
    "A" * 100,
    "abc-def_ghi:jkl/012",
]
INVALID_IDS = [
    "",
    "A" * 101,
    "has space",
    "newline\n",
    "%0a",
    "semi;colon",
    "quote'",
    'dquote"',
    "back\\slash",
    "unicodeé",
    "tab\t",
    "at@sign",
]


@pytest.mark.parametrize("vid", VALID_IDS)
def test_variant_id_valid_values_accepted(vid):
    req = DiscountSimulatorRequest(variant_id=vid, discount_percent=10.0)
    assert req.variant_id == vid


@pytest.mark.parametrize("vid", INVALID_IDS)
def test_variant_id_invalid_values_rejected(vid):
    with pytest.raises(ValidationError):
        DiscountSimulatorRequest(variant_id=vid, discount_percent=10.0)


def test_variant_id_trailing_newline_rejected():
    """Pattern anchoring: 'abc\\n' must fail even if regex $ accepts \\n."""
    with pytest.raises(ValidationError):
        DiscountSimulatorRequest(variant_id="abc\n", discount_percent=5.0)


@pytest.mark.parametrize(
    "pct",
    [
        -0.01,
        100.01,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_discount_percent_out_of_range_rejected(pct):
    with pytest.raises(ValidationError):
        DiscountSimulatorRequest(
            variant_id="gid://shopify/ProductVariant/1", discount_percent=pct
        )


@pytest.mark.parametrize("pct", [0.0, 100.0, 50.5])
def test_discount_percent_boundary_values_accepted(pct):
    req = DiscountSimulatorRequest(
        variant_id="gid://shopify/ProductVariant/1", discount_percent=pct
    )
    assert req.discount_percent == pct


def test_discount_percent_string_rejected():
    with pytest.raises(ValidationError):
        DiscountSimulatorRequest(
            variant_id="gid://shopify/ProductVariant/1", discount_percent="abc"
        )


# ── REQ-002 / Decimal precision ────────────────────────────────────────────


def test_discount_money_output_is_string_never_float_repr():
    """0.30000000000000004 must never appear in output."""
    r = evaluate_discount(Decimal("19.99"), Decimal("10.00"), 33.33)
    # check all money fields are plain decimal strings
    for field_name in ("base_price", "discounted_price", "margin_remaining"):
        val = getattr(r, field_name)
        if val is not None:
            assert "." in val
            # no float garbage
            assert "e" not in val.lower()
            assert len(val.split(".")[1]) == 2


def test_discount_break_even_is_valid():
    """Contract: discounted_price == unit_cost -> margin=0.00 -> valid True.
    The implementation uses >= 0 so equality is VALID.
    """
    r = evaluate_discount(Decimal("50.00"), Decimal("40.00"), 20)
    assert r.valid is True
    assert r.margin_remaining == "0.00"


def test_discount_unit_cost_zero_no_zerodivision():
    """max_safe_discount_pct when unit_cost=0: should be 100 and not raise."""
    r = evaluate_discount(Decimal("50.00"), Decimal("0.00"), 50)
    # discounted_price 25.00 > 0.00 -> valid
    assert r.valid is True


def test_discount_base_price_zero_no_zerodivision():
    r = evaluate_discount(Decimal("0.00"), Decimal("0.00"), 0)
    # discounted 0.00 >= cost 0.00 -> valid
    assert r.valid is True
    r2 = evaluate_discount(Decimal("0.00"), Decimal("1.00"), 0)
    assert r2.valid is False
    assert r2.max_safe_discount_pct == "0.00"


def test_parse_variant_pricing_null_inventory_item():
    """inventoryItem: null -> unit_cost=None, not an exception."""
    price, cost = parse_variant_pricing({"price": "9.99", "inventoryItem": None})
    assert price == Decimal("9.99")
    assert cost is None


def test_parse_variant_pricing_non_numeric_amount_returns_none():
    price, cost = parse_variant_pricing(
        {"price": "9.99", "inventoryItem": {"unitCost": {"amount": "n/a"}}}
    )
    assert cost is None


def test_parse_variant_pricing_negative_price_returns_none():
    price, _ = parse_variant_pricing({"price": "-5.00"})
    assert price is None


# ── REQ-001 / travel window edge cases ────────────────────────────────────


def test_cancelled_event_excluded_from_windows():
    event = {
        "summary": "Trip",
        "start": {"date": "2026-10-15"},
        "end": {"date": "2026-10-20"},
        "status": "cancelled",
    }
    assert travel_windows([event]) == []


def test_timed_event_no_start_date_excluded():
    event = {
        "summary": "Call",
        "start": {"dateTime": "2026-10-15T09:00:00Z"},
        "end": {"dateTime": "2026-10-15T10:00:00Z"},
    }
    assert travel_windows([event]) == []


def test_single_all_day_event_one_day_span_excluded():
    """start=Oct15, end=Oct16 means (end-start).days == 1, not > 1."""
    event = {
        "summary": "Day off",
        "start": {"date": "2026-10-15"},
        "end": {"date": "2026-10-16"},
    }
    assert travel_windows([event]) == []


def test_two_day_span_is_travel_window():
    event = {
        "summary": "Trip",
        "start": {"date": "2026-10-15"},
        "end": {"date": "2026-10-17"},
    }
    windows = travel_windows([event])
    assert len(windows) == 1
    start, end, title = windows[0]
    assert str(start) == "2026-10-15"
    assert str(end) == "2026-10-17"
    assert title == "Trip"


def test_event_with_malformed_date_excluded():
    event = {
        "summary": "Bad",
        "start": {"date": "not-a-date"},
        "end": {"date": "2026-10-20"},
    }
    assert travel_windows([event]) == []


def test_event_with_missing_summary_uses_fallback():
    event = {"start": {"date": "2026-10-15"}, "end": {"date": "2026-10-17"}}
    windows = travel_windows([event])
    assert windows[0][2] == "(no title)"


# ── REQ-003 / order matcher edge cases ────────────────────────────────────

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
    {
        "id": "gid://shopify/Order/7",
        "name": "#104",
        "customer": {"displayName": "A.B (Jr)"},
    },
]


def _thread(snippet, tid="t1"):
    return {"id": tid, "snippet": snippet, "historyId": "1"}


def test_word_boundary_prevents_1042_matching_10420():
    """#10420 must not match order #1042."""
    threads = match_threads_to_orders([_thread("order #10420")], ORDERS)
    assert threads[0].matched_order_id is None


def test_104_does_not_match_1042_via_hash():
    """#1042 in snippet must not match order #104 (and vice versa)."""
    threads = match_threads_to_orders([_thread("ref #104")], ORDERS)
    assert threads[0].matched_order_name == "#104"


def test_regex_metacharacters_in_customer_name_do_not_raise():
    """Customer name 'A.B (Jr)' contains . and () which are regex metacharacters."""
    threads = match_threads_to_orders(
        [_thread("Hello A.B (Jr) your order is ready")], ORDERS
    )
    # Should not raise re.error; match may or may not occur depending on escaping
    # The important contract is no exception.
    assert isinstance(threads[0], ThreadMeta)


def test_single_word_customer_names_not_matched():
    """'Sam' is a single token and must not be matched by name."""
    threads = match_threads_to_orders([_thread("hi Sam still waiting")], ORDERS)
    assert threads[0].matched_order_id is None


def test_empty_snippet_produces_unmatched_thread():
    threads = match_threads_to_orders([_thread("")], ORDERS)
    assert threads[0].matched_order_id is None
    assert threads[0].snippet == ""


def test_none_snippet_produces_empty_string_in_output():
    threads = match_threads_to_orders([{"id": "x", "snippet": None}], ORDERS)
    assert threads[0].snippet == ""
    assert threads[0].matched_order_id is None


def test_empty_orders_list_produces_unmatched_threads():
    threads = match_threads_to_orders([_thread("#1042")], [])
    assert threads[0].matched_order_id is None


def test_html_entities_decoded_before_matching():
    threads = match_threads_to_orders(
        [_thread("Jane Smith &amp; co: it&#39;s order #1042")], ORDERS
    )
    assert threads[0].match_confidence == "high"
    assert "&amp;" not in threads[0].snippet


def test_rank_threads_reverses_input_order():
    t1 = ThreadMeta(id="new", snippet="a")
    t2 = ThreadMeta(id="old", snippet="b")
    ranked = rank_threads([t1, t2])
    assert [t.id for t in ranked] == ["old", "new"]


def test_rank_threads_single_item_unchanged():
    t = ThreadMeta(id="only", snippet="x")
    assert rank_threads([t]) == [t]


def test_rank_threads_empty_list_returns_empty():
    assert rank_threads([]) == []


def test_threadmeta_has_no_last_message_from_or_date():
    """Decision A: these fields were dropped. Assert they are absent from model_fields."""
    fields = set(ThreadMeta.model_fields.keys())
    assert "last_message_from" not in fields
    assert "last_message_date" not in fields


# ── providers.parse_calendar_result / parse_gmail_result ──────────────────

import httpx
from src.services.shopify.providers import (
    GMAIL_UNANSWERED_QUERY,
    parse_calendar_result,
    parse_gmail_result,
)
from src.tools.base import ProviderNotLinked, ProviderReauthRequired, ToolError


def test_parse_calendar_not_linked_returns_not_connected():
    cal = parse_calendar_result(ProviderNotLinked("google"))
    assert cal.connected is False
    assert cal.partial_failures == []


def test_parse_calendar_reauth_returns_partial_failure():
    cal = parse_calendar_result(ProviderReauthRequired("google"))
    assert cal.needs_reauth is True
    assert "calendar" in cal.partial_failures


def test_parse_calendar_tool_error_not_swallowed():
    """ToolError (not ProviderNotLinked/Reauth) is partial failure, not raise."""
    cal = parse_calendar_result(ToolError("provider_http_error", "boom"))
    assert cal.connected is True
    assert cal.needs_reauth is False
    assert "calendar" in cal.partial_failures


def test_parse_calendar_provider_not_linked_checked_before_tool_error():
    """ProviderNotLinked subclasses ToolError; check specific first or it leaks."""
    cal = parse_calendar_result(ProviderNotLinked("google"))
    # must not report partial_failures as ToolError path would
    assert cal.partial_failures == []


def test_parse_calendar_unexpected_exception_reraises():
    with pytest.raises(RuntimeError):
        parse_calendar_result(RuntimeError("unexpected"))


def test_parse_calendar_happy_path_returns_events():
    body = {
        "items": [
            {
                "summary": "Trip",
                "start": {"date": "2026-11-01"},
                "end": {"date": "2026-11-05"},
            }
        ]
    }
    cal = parse_calendar_result(body)
    assert len(cal.events) == 1
    assert cal.connected is True


def test_parse_calendar_next_page_token_sets_truncated():
    body = {"items": [], "nextPageToken": "abc"}
    cal = parse_calendar_result(body)
    assert "calendar_truncated" in cal.partial_failures


def test_parse_gmail_not_linked_returns_not_connected():
    result = parse_gmail_result(ProviderNotLinked("google"))
    assert result.connected is False
    assert result.threads == []


def test_parse_gmail_reauth_returns_partial_failure():
    result = parse_gmail_result(ProviderReauthRequired("google"))
    assert result.needs_reauth is True
    assert "gmail" in result.partial_failures


def test_parse_gmail_provider_not_linked_checked_before_tool_error():
    """ProviderNotLinked subclasses ToolError; must not be caught by ToolError branch."""
    result = parse_gmail_result(ProviderNotLinked("google"))
    assert result.partial_failures == []


def test_parse_gmail_httpx_error_is_partial_failure():
    result = parse_gmail_result(httpx.ConnectError("x"))
    assert result.connected is True
    assert "gmail" in result.partial_failures


def test_parse_gmail_next_page_token_sets_truncated():
    body = {"threads": [{"id": "a", "snippet": "hi"}], "nextPageToken": "tok"}
    result = parse_gmail_result(body)
    assert result.threads_truncated is True
    assert len(result.threads) == 1


def test_parse_gmail_no_token_not_truncated():
    body = {"threads": []}
    result = parse_gmail_result(body)
    assert result.threads_truncated is False


def test_gmail_query_constant_matches_decision_a():
    """The pre-filter query must be exactly what Decision A specifies."""
    assert GMAIL_UNANSWERED_QUERY == "in:inbox -from:me older_than:24h"
