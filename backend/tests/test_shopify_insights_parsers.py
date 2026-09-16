"""Tests for the insights additions to backend/src/services/shopify/parsers.py.

All pure functions — no I/O, no mocks needed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.services.shopify.parsers import (
    _shop_zone,
    day_window,
    parse_insights,
    window_bounds,
)

# ── _shop_zone / day_window fallback ────────────────────────────────────────


def test_shop_zone_falls_back_to_utc_on_garbage_timezone():
    zone = _shop_zone("Not/A_Real_Zone")

    assert str(zone) == "UTC"


def test_day_window_still_works_after_shop_zone_extraction():
    now = datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)

    start, end = day_window("UTC", now)

    assert start == "2026-09-14T00:00:00Z"
    assert end == "2026-09-14T15:00:00Z"


# ── window_bounds ────────────────────────────────────────────────────────


def test_window_bounds_produces_days_consecutive_local_dates_ending_today():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

    bounds = window_bounds("UTC", now, 7)

    assert bounds.local_dates == [
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
        "2026-09-12",
        "2026-09-13",
        "2026-09-14",
    ]


def test_window_bounds_falls_back_to_utc_on_bad_timezone():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

    bounds = window_bounds("Bogus/Zone", now, 7)

    assert str(bounds.zone) == "UTC"
    assert len(bounds.local_dates) == 7


def test_window_bounds_across_dst_transition_still_yields_exact_day_count():
    # US spring-forward 2026-03-08. A naive timedelta-based day walker can
    # under/overshoot across this boundary; local-calendar-day iteration
    # must not.
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

    bounds = window_bounds("America/New_York", now, 30)

    assert len(bounds.local_dates) == 30
    assert (
        len(set(bounds.local_dates)) == 30
    )  # every date distinct, none skipped/duplicated
    assert bounds.local_dates == sorted(bounds.local_dates)


def test_window_bounds_end_iso_is_bare_z_format():
    now = datetime(2026, 9, 14, 12, 30, 45, tzinfo=timezone.utc)

    bounds = window_bounds("UTC", now, 7)

    assert bounds.end_iso.endswith("Z")
    assert "+00:00" not in bounds.end_iso


# ── parse_insights: bucketing ───────────────────────────────────────────


def _raw(orders, truncated=False, covered_through=None, partial_failures=None):
    return {
        "orders": orders,
        "truncated": truncated,
        "covered_through": covered_through,
        "partial_failures": partial_failures or [],
    }


def _order(created_at: str, amount: str) -> dict:
    return {
        "id": "gid://shopify/Order/1",
        "createdAt": created_at,
        "currentTotalPriceSet": {"shopMoney": {"amount": amount}},
    }


def test_parse_insights_buckets_order_into_correct_local_date():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 3)
    raw = _raw([_order("2026-09-13T10:00:00Z", "50.00")])

    core = parse_insights(raw, bounds, "USD")

    point = next(p for p in core.points if p.date == "2026-09-13")
    assert point.revenue_amount == "50.00"
    assert point.order_count == 1


def test_parse_insights_assigns_late_utc_order_to_next_local_date_for_positive_offset():
    # 23:30 UTC on 09-13 is 08:30 local the NEXT day in UTC+9.
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("Asia/Tokyo", now, 3)
    raw = _raw([_order("2026-09-13T23:30:00Z", "10.00")])

    core = parse_insights(raw, bounds, "JPY")

    point = next(p for p in core.points if p.date == "2026-09-14")
    assert point.order_count == 1


def test_parse_insights_zero_order_complete_days_render_as_zero():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 3)
    raw = _raw([])

    core = parse_insights(raw, bounds, "USD")

    non_partial = [p for p in core.points if not p.is_partial_day]
    assert all(p.revenue_amount == "0.00" and p.order_count == 0 for p in non_partial)


def test_parse_insights_last_point_is_marked_partial_day():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 3)
    raw = _raw([])

    core = parse_insights(raw, bounds, "USD")

    assert core.points[-1].is_partial_day is True
    assert all(not p.is_partial_day for p in core.points[:-1])


def test_parse_insights_unparsable_amount_appends_partial_failure_and_does_not_crash():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 3)
    raw = _raw([_order("2026-09-13T10:00:00Z", "not-a-number")])

    core = parse_insights(raw, bounds, "USD")

    assert "revenue_amount" in core.partial_failures


def test_parse_insights_decimal_accumulation_is_exact():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 3)
    raw = _raw(
        [
            _order("2026-09-13T01:00:00Z", "0.10"),
            _order("2026-09-13T02:00:00Z", "0.20"),
        ]
    )

    core = parse_insights(raw, bounds, "USD")

    point = next(p for p in core.points if p.date == "2026-09-13")
    assert point.revenue_amount == "0.30"


# ── parse_insights: truncation (BLOCKER B1 regression) ──────────────────


def test_parse_insights_truncated_marks_covered_through_day_onwards_as_gaps():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 5)  # 09-10 .. 09-14
    raw = _raw(
        [_order("2026-09-11T05:00:00Z", "100.00")],
        truncated=True,
        covered_through="2026-09-11T05:00:00Z",
    )

    core = parse_insights(raw, bounds, "USD")

    by_date = {p.date: p for p in core.points}
    assert by_date["2026-09-10"].revenue_amount == "0.00"  # fully covered: real data
    # The boundary day itself is a gap, not "100.00": orders are fetched
    # ascending, so the fetch stopped partway through 09-11 and that day's
    # total is knowably incomplete — publishing it would be the false
    # revenue cliff the truncation rule exists to prevent.
    assert by_date["2026-09-11"].revenue_amount is None
    assert by_date["2026-09-11"].order_count is None
    assert by_date["2026-09-12"].revenue_amount is None  # gap
    assert by_date["2026-09-12"].order_count is None
    assert by_date["2026-09-13"].revenue_amount is None  # gap
    assert by_date["2026-09-14"].revenue_amount is None  # gap (also partial day)


def test_parse_insights_truncated_with_no_pages_fetched_marks_everything_gap():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 3)
    raw = _raw([], truncated=True, covered_through=None)

    core = parse_insights(raw, bounds, "USD")

    assert all(p.revenue_amount is None for p in core.points)


def test_parse_insights_truncated_window_has_no_summary():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 14)
    raw = _raw([], truncated=True, covered_through="2026-09-05T00:00:00Z")

    core = parse_insights(raw, bounds, "USD")

    assert core.summary is None


# ── _build_summary (via parse_insights) ──────────────────────────────────


def _orders_for_days(day_amounts: dict[str, str]) -> list[dict]:
    return [_order(f"{d}T10:00:00Z", amt) for d, amt in day_amounts.items()]


def test_summary_present_and_computes_window_totals_when_not_truncated():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 7)
    raw = _raw(
        _orders_for_days(
            {
                "2026-09-08": "10.00",
                "2026-09-09": "20.00",
                "2026-09-10": "30.00",
                "2026-09-11": "40.00",
                "2026-09-12": "50.00",
                "2026-09-13": "60.00",
            }
        )
    )

    core = parse_insights(raw, bounds, "USD")

    assert core.summary is not None
    assert core.summary.window_revenue == "210.00"
    assert core.summary.window_order_count == 6
    assert core.summary.completed_day_count == 6  # 09-14 excluded as partial day


def test_summary_direction_flat_within_band():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 7)
    # 6 completed days, all equal -> 0% change -> flat
    raw = _raw(
        _orders_for_days(
            {
                "2026-09-08": "100.00",
                "2026-09-09": "100.00",
                "2026-09-10": "100.00",
                "2026-09-11": "100.00",
                "2026-09-12": "100.00",
                "2026-09-13": "100.00",
            }
        )
    )

    core = parse_insights(raw, bounds, "USD")

    assert core.summary.direction == "flat"
    assert core.summary.prior_period_change_pct == 0.0


def test_summary_direction_up_beyond_five_percent():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 7)
    raw = _raw(
        _orders_for_days(
            {
                "2026-09-08": "10.00",
                "2026-09-09": "10.00",
                "2026-09-10": "10.00",
                "2026-09-11": "100.00",
                "2026-09-12": "100.00",
                "2026-09-13": "100.00",
            }
        )
    )

    core = parse_insights(raw, bounds, "USD")

    assert core.summary.direction == "up"
    assert core.summary.prior_period_change_pct > 5


def test_summary_unknown_when_fewer_than_min_half_days():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    # 3-day window: 2 completed days (09-13 is the partial day) -> half=1 <
    # _MIN_HALF_DAYS(3) -> unknown.
    bounds = window_bounds("UTC", now, 3)
    raw = _raw(_orders_for_days({"2026-09-12": "10.00"}))

    core = parse_insights(raw, bounds, "USD")

    assert core.summary.direction == "unknown"
    assert core.summary.prior_period_change_pct is None


def test_summary_best_and_worst_day_among_completed_days():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    bounds = window_bounds("UTC", now, 7)
    raw = _raw(
        _orders_for_days(
            {
                "2026-09-08": "10.00",
                "2026-09-09": "999.00",
                "2026-09-10": "5.00",
                "2026-09-11": "20.00",
                "2026-09-12": "20.00",
                "2026-09-13": "20.00",
            }
        )
    )

    core = parse_insights(raw, bounds, "USD")

    assert core.summary.best_day == "2026-09-09"
    assert core.summary.worst_day == "2026-09-10"
