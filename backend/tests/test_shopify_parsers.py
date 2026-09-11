"""Tests for backend/src/services/shopify/parsers.py.

Pure-function characterisation tests — no I/O, no DB, no network.
Focus areas:
  * day_window: timezone fallback, and the recent format change from
    isoformat()+00:00 → strftime Z-suffix (regression guard).
  * _to_decimal / _quantize: malformed input, rounding.
  * parse_dashboard: truncation, partial_failures accumulation, AOV edge
    cases, recent_orders cap, low-stock gating.
  * _parse_order: missing / malformed fields.
  * _count_low_stock: tracked gate, multi-location accumulation, quantity
    name filtering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.services.shopify.parsers import (
    ORDERS_TRUNCATION_LIMIT,
    RECENT_ORDERS_LIMIT,
    _count_low_stock,
    _parse_order,
    _quantize,
    _to_decimal,
    day_window,
    parse_dashboard,
)


# ── day_window ────────────────────────────────────────────────────────────


def test_day_window_returns_z_suffix_not_utc_offset():
    """Regression guard for the isoformat() → strftime change.

    isoformat() on a UTC datetime produces "…+00:00"; Shopify's search
    grammar can mis-parse the unquoted "+00:00" as a second field
    delimiter in `created_at:>=…`, silently emptying the day's KPIs.
    The new format must end with a bare "Z", never "+00:00".
    """
    now = datetime(2026, 9, 11, 15, 30, 0, tzinfo=timezone.utc)

    start, end = day_window("UTC", now)

    assert start.endswith("Z"), f"start {start!r} must end with 'Z'"
    assert end.endswith("Z"), f"end {end!r} must end with 'Z'"
    assert "+00:00" not in start
    assert "+00:00" not in end


def test_day_window_utc_midnight_is_day_start():
    now = datetime(2026, 9, 11, 15, 30, 0, tzinfo=timezone.utc)

    start, end = day_window("UTC", now)

    assert start == "2026-09-11T00:00:00Z"
    assert end == "2026-09-11T15:30:00Z"


def test_day_window_offsets_midnight_to_local_timezone():
    """America/New_York is UTC-4 in summer (EDT).

    UTC 03:00 on Sept 11 is 2026-09-10 23:00 EDT, so local midnight is
    2026-09-10 00:00 EDT = 2026-09-10 04:00 UTC.
    """
    now = datetime(2026, 9, 11, 3, 0, 0, tzinfo=timezone.utc)

    start, end = day_window("America/New_York", now)

    assert start == "2026-09-10T04:00:00Z"
    assert end == "2026-09-11T03:00:00Z"


@pytest.mark.parametrize(
    "bad_tz",
    [
        "Not/ATimezone",
        "completely_invalid",
        "",
    ],
)
def test_day_window_falls_back_to_utc_for_unrecognised_timezone(bad_tz):
    """A corrupted shop_timezone value must not raise or blank the dashboard.

    The fallback is UTC, so midnight == start of the UTC calendar day.
    """
    now = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)

    start, end = day_window(bad_tz, now)

    assert start == "2026-09-11T00:00:00Z"
    assert end == "2026-09-11T10:00:00Z"


def test_day_window_format_has_no_microseconds():
    """Shopify date filters do not accept microseconds."""
    now = datetime(2026, 9, 11, 12, 34, 56, 789000, tzinfo=timezone.utc)

    start, end = day_window("UTC", now)

    assert "." not in start
    assert "." not in end


# ── _to_decimal ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "amount,expected",
    [
        ("10.50", Decimal("10.50")),
        ("0", Decimal("0")),
        ("1000000.99", Decimal("1000000.99")),
        ("-5.00", Decimal("-5.00")),
    ],
)
def test_to_decimal_parses_valid_strings(amount, expected):
    assert _to_decimal(amount) == expected


def test_to_decimal_returns_none_for_none_input():
    assert _to_decimal(None) is None


@pytest.mark.parametrize(
    "bad_amount",
    ["", "abc", "12.34.56", "$100"],
)
def test_to_decimal_returns_none_for_malformed_input(bad_amount):
    """A malformed wire value must not raise — it silently under-totals,
    which parse_dashboard surfaces via partial_failures instead of crashing.
    """
    assert _to_decimal(bad_amount) is None


# ── _quantize ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("10"), "10.00"),
        (Decimal("10.5"), "10.50"),
        (Decimal("10.555"), "10.56"),  # ROUND_HALF_UP
        (Decimal("10.554"), "10.55"),
        (Decimal("0.005"), "0.01"),    # ROUND_HALF_UP rounds 0.005 up
        (Decimal("0"), "0.00"),
    ],
)
def test_quantize_formats_to_two_decimal_places(value, expected):
    assert _quantize(value) == expected


# ── _count_low_stock ──────────────────────────────────────────────────────


def test_count_low_stock_returns_zero_for_empty_list():
    assert _count_low_stock([], threshold=5) == 0


def test_count_low_stock_skips_untracked_variants():
    """Untracked inventory should never contribute to the low-stock count."""
    variants = [
        {"inventoryItem": {"tracked": False, "inventoryLevels": {"edges": []}}}
    ]

    result = _count_low_stock(variants, threshold=5)

    assert result == 0


def test_count_low_stock_skips_variant_with_no_inventory_item():
    variants = [{}]

    result = _count_low_stock(variants, threshold=5)

    assert result == 0


def test_count_low_stock_counts_tracked_variant_below_threshold():
    variants = [
        {
            "inventoryItem": {
                "tracked": True,
                "inventoryLevels": {
                    "edges": [
                        {
                            "node": {
                                "quantities": [
                                    {"name": "available", "quantity": 3}
                                ]
                            }
                        }
                    ]
                },
            }
        }
    ]

    result = _count_low_stock(variants, threshold=5)

    assert result == 1


def test_count_low_stock_does_not_count_variant_at_or_above_threshold():
    """available < threshold — exactly at threshold must NOT be counted."""
    variants = [
        {
            "inventoryItem": {
                "tracked": True,
                "inventoryLevels": {
                    "edges": [
                        {
                            "node": {
                                "quantities": [
                                    {"name": "available", "quantity": 5}
                                ]
                            }
                        }
                    ]
                },
            }
        }
    ]

    result = _count_low_stock(variants, threshold=5)

    assert result == 0


def test_count_low_stock_accumulates_available_across_locations():
    """A variant spread across two locations must sum their quantities."""
    variants = [
        {
            "inventoryItem": {
                "tracked": True,
                "inventoryLevels": {
                    "edges": [
                        {
                            "node": {
                                "quantities": [
                                    {"name": "available", "quantity": 2}
                                ]
                            }
                        },
                        {
                            "node": {
                                "quantities": [
                                    {"name": "available", "quantity": 3}
                                ]
                            }
                        },
                    ]
                },
            }
        }
    ]

    result = _count_low_stock(variants, threshold=10)

    # 2 + 3 = 5, which is < 10
    assert result == 1


def test_count_low_stock_ignores_non_available_quantity_names():
    """Only quantities named 'available' count toward stock level."""
    variants = [
        {
            "inventoryItem": {
                "tracked": True,
                "inventoryLevels": {
                    "edges": [
                        {
                            "node": {
                                "quantities": [
                                    {"name": "on_hand", "quantity": 100},
                                    {"name": "committed", "quantity": 50},
                                    {"name": "available", "quantity": 1},
                                ]
                            }
                        }
                    ]
                },
            }
        }
    ]

    result = _count_low_stock(variants, threshold=5)

    # Only available=1 counts, not on_hand=100
    assert result == 1


def test_count_low_stock_handles_missing_quantities_list():
    """A node with no quantities key must not raise."""
    variants = [
        {
            "inventoryItem": {
                "tracked": True,
                "inventoryLevels": {
                    "edges": [{"node": {}}]
                },
            }
        }
    ]

    result = _count_low_stock(variants, threshold=5)

    # available defaults to 0 which is < 5
    assert result == 1


# ── _parse_order ──────────────────────────────────────────────────────────


def _order_node(**overrides):
    base = {
        "id": "gid://shopify/Order/123",
        "name": "#1001",
        "createdAt": "2026-09-11T10:00:00Z",
        "customer": {"displayName": "Jane Smith"},
        "lineItems": {"totalCount": 3},
        "currentTotalPriceSet": {
            "shopMoney": {"amount": "49.99", "currencyCode": "USD"}
        },
    }
    base.update(overrides)
    return base


def test_parse_order_maps_all_fields_from_full_node():
    node = _order_node()

    order = _parse_order(node)

    assert order.id == "gid://shopify/Order/123"
    assert order.order_number == "#1001"
    assert order.customer_name == "Jane Smith"
    assert order.item_count == 3
    assert order.total_amount == "49.99"
    assert order.currency_code == "USD"
    assert order.created_at == "2026-09-11T10:00:00Z"


def test_parse_order_sets_customer_name_none_when_customer_absent():
    node = _order_node(customer=None)

    order = _parse_order(node)

    assert order.customer_name is None


def test_parse_order_falls_back_to_zero_on_malformed_amount():
    """A bad wire amount must render as $0.00, not raise."""
    node = _order_node(
        currentTotalPriceSet={
            "shopMoney": {"amount": "not-a-number", "currencyCode": "USD"}
        }
    )

    order = _parse_order(node)

    assert order.total_amount == "0.00"


def test_parse_order_returns_zero_item_count_when_line_items_absent():
    node = _order_node(lineItems=None)

    order = _parse_order(node)

    assert order.item_count == 0


def test_parse_order_handles_fully_empty_node():
    order = _parse_order({})

    assert order.id == ""
    assert order.order_number == ""
    assert order.total_amount == "0.00"
    assert order.item_count == 0
    assert order.customer_name is None


# ── parse_dashboard ───────────────────────────────────────────────────────


def _raw_with_orders(orders, **kwargs):
    return {"orders": orders, "orders_count": len(orders), **kwargs}


def test_parse_dashboard_computes_revenue_for_empty_order_list():
    raw = _raw_with_orders([])

    result = parse_dashboard(raw, "USD")

    assert result.revenue_amount == "0.00"
    assert result.truncated is False
    assert result.connected is True


def test_parse_dashboard_sums_multiple_order_amounts():
    orders = [
        {
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "10.00", "currencyCode": "USD"}
            }
        },
        {
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "25.50", "currencyCode": "USD"}
            }
        },
    ]
    raw = _raw_with_orders(orders)

    result = parse_dashboard(raw, "USD")

    assert result.revenue_amount == "35.50"


def test_parse_dashboard_sets_truncated_when_has_next_page():
    raw = _raw_with_orders([], orders_has_next_page=True)

    result = parse_dashboard(raw, "USD")

    assert result.truncated is True
    assert result.revenue_amount is None


def test_parse_dashboard_sets_truncated_when_orders_at_page_limit():
    """When len(orders) >= page_limit, the figure is not safe to report."""
    orders = [
        {
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "1.00", "currencyCode": "USD"}
            }
        }
    ] * 5
    raw = _raw_with_orders(orders, orders_page_limit=5)

    result = parse_dashboard(raw, "USD")

    assert result.truncated is True
    assert result.revenue_amount is None


def test_parse_dashboard_uses_fallback_truncation_limit_when_not_in_raw():
    """orders_page_limit absent → uses ORDERS_TRUNCATION_LIMIT (250)."""
    # 249 orders — just under the fallback limit, should NOT truncate
    orders = [
        {
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "1.00", "currencyCode": "USD"}
            }
        }
    ] * 249
    raw = {"orders": orders, "orders_count": 249}

    result = parse_dashboard(raw, "USD")

    assert result.truncated is False
    assert result.revenue_amount == "249.00"


def test_parse_dashboard_appends_revenue_amount_to_partial_failures_on_bad_money():
    """When one order has an unparsable amount, partial_failures must include
    'revenue_amount' so the frontend can flag the KPI as approximate.
    """
    orders = [
        {
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "bad-value", "currencyCode": "USD"}
            }
        },
        {
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "10.00", "currencyCode": "USD"}
            }
        },
    ]
    raw = _raw_with_orders(orders)

    result = parse_dashboard(raw, "USD")

    assert "revenue_amount" in result.partial_failures


def test_parse_dashboard_does_not_duplicate_revenue_amount_partial_failure():
    """If the raw payload already contains 'revenue_amount' in
    partial_failures, it must not appear twice.
    """
    raw = _raw_with_orders(
        [
            {
                "currentTotalPriceSet": {
                    "shopMoney": {"amount": "BAD", "currencyCode": "USD"}
                }
            }
        ],
        partial_failures=["revenue_amount"],
    )

    result = parse_dashboard(raw, "USD")

    assert result.partial_failures.count("revenue_amount") == 1


def test_parse_dashboard_preserves_existing_partial_failures_from_raw():
    raw = _raw_with_orders([], partial_failures=["productVariants"])

    result = parse_dashboard(raw, "USD")

    assert "productVariants" in result.partial_failures


def test_parse_dashboard_order_count_approximate_false_when_exact():
    raw = _raw_with_orders([], orders_count_precision="EXACT")

    result = parse_dashboard(raw, "USD")

    assert result.order_count_approximate is False


def test_parse_dashboard_order_count_approximate_true_when_not_exact():
    raw = _raw_with_orders([], orders_count_precision="APPROXIMATE")

    result = parse_dashboard(raw, "USD")

    assert result.order_count_approximate is True


def test_parse_dashboard_order_count_approximate_false_when_precision_absent():
    """Absent precision key means the count is trusted as exact."""
    raw = _raw_with_orders([])

    result = parse_dashboard(raw, "USD")

    assert result.order_count_approximate is False


def test_parse_dashboard_computes_average_order_value():
    orders = [
        {
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "30.00", "currencyCode": "USD"}
            }
        }
    ] * 3
    raw = _raw_with_orders(orders)

    result = parse_dashboard(raw, "USD")

    assert result.average_order_value == "30.00"


def test_parse_dashboard_average_order_value_is_none_when_truncated():
    raw = _raw_with_orders([], orders_has_next_page=True)

    result = parse_dashboard(raw, "USD")

    assert result.average_order_value is None


def test_parse_dashboard_average_order_value_is_none_when_order_count_zero():
    """Division by zero must not raise."""
    raw = {"orders": [], "orders_count": 0}

    result = parse_dashboard(raw, "USD")

    assert result.average_order_value is None


def test_parse_dashboard_caps_recent_orders_at_limit():
    """Only the first RECENT_ORDERS_LIMIT (20) orders appear in recent_orders."""
    orders = [
        {
            "id": f"gid://shopify/Order/{i}",
            "name": f"#100{i}",
            "createdAt": "2026-09-11T00:00:00Z",
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "1.00", "currencyCode": "USD"}
            },
        }
        for i in range(25)
    ]
    raw = _raw_with_orders(orders, orders_page_limit=250)

    result = parse_dashboard(raw, "USD")

    assert len(result.recent_orders) == RECENT_ORDERS_LIMIT


def test_parse_dashboard_low_stock_is_none_when_productVariants_in_partial_failures():
    """A failed productVariants alias must yield None, not a confident 0."""
    raw = _raw_with_orders(
        [],
        partial_failures=["productVariants"],
        variants=[],
    )

    result = parse_dashboard(raw, "USD")

    assert result.low_stock_sku_count is None


def test_parse_dashboard_low_stock_is_none_when_variants_has_next_page():
    raw = _raw_with_orders([], variants=[], variants_has_next_page=True)

    result = parse_dashboard(raw, "USD")

    assert result.low_stock_sku_count is None


def test_parse_dashboard_low_stock_count_when_variants_complete():
    variants = [
        {
            "inventoryItem": {
                "tracked": True,
                "inventoryLevels": {
                    "edges": [
                        {
                            "node": {
                                "quantities": [
                                    {"name": "available", "quantity": 2}
                                ]
                            }
                        }
                    ]
                },
            }
        }
    ]
    raw = _raw_with_orders([], variants=variants)

    result = parse_dashboard(raw, "USD")

    assert result.low_stock_sku_count == 1


def test_parse_dashboard_currency_code_propagated():
    raw = _raw_with_orders([])

    result = parse_dashboard(raw, "GBP")

    assert result.currency_code == "GBP"
