"""Wire-to-schema parsing for the Shopify dashboard. Pure functions, no I/O.

Revenue KPI definition (documented here because it drives every choice
below): gross revenue from submitted, non-test orders placed in the shop's
current calendar day (shop timezone). Does NOT exclude refunds or
discounts — it will not reconcile with Shopify Analytics, which nets those
post-order. The UI labels the figure accordingly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...schemas.shopify import (
    ShopifyDashboard,
    ShopifyInsightPoint,
    ShopifyInsightSummary,
    ShopifyOrder,
)

_log = logging.getLogger(__name__)

# Fallback page size used when the raw payload does not declare the
# `orders_page_limit` it was fetched with. Once a full page of orders comes
# back, we stop trusting it to represent the whole day's revenue and mark
# the figure truncated instead of silently under-reporting. The live value
# comes from client.ORDERS_PAGE_LIMIT, carried in the payload rather than
# imported, so this pure module never depends on the transport module.
ORDERS_TRUNCATION_LIMIT = 250

RECENT_ORDERS_LIMIT = 20

LOW_STOCK_DEFAULT_THRESHOLD = 5


def _shop_zone(tz: str) -> ZoneInfo:
    """Resolve a stored IANA timezone name, falling back to UTC rather than
    raising — a bad stored value must not blank the dashboard or insights.

    Single fallback/warning path shared by day_window and window_bounds. A
    caller that loops per-order (e.g. parse_insights bucketing hundreds of
    orders) must call this ONCE and thread the result through — calling it
    per-order would re-emit the warning up to once per order on a corrupt
    timezone.
    """
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        # Silent by design (a bad stored value must not blank the
        # dashboard), but "silent to the user" must not mean "silent to
        # the operator" — without this, a corrupted shop_timezone value
        # quietly shifts every "today" boundary with nothing in the logs
        # to explain why revenue/order-count look off.
        _log.warning("Unrecognised Shopify shop timezone %r — falling back to UTC", tz)
        return ZoneInfo("UTC")


def day_window(tz: str, now: datetime) -> tuple[str, str]:
    """Local midnight -> now, in the shop's IANA timezone, as UTC ISO-8601
    bounds. Falls back to UTC for an unrecognised timezone rather than
    raising — a bad stored value must not blank the dashboard.
    """
    zone = _shop_zone(tz)
    local_now = now.astimezone(zone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_utc = local_midnight.astimezone(timezone.utc)
    day_end_utc = local_now.astimezone(timezone.utc)
    # Shopify's search grammar wants a bare "Z" suffix, not the "+00:00"
    # offset datetime.isoformat() produces — an unquoted "+00:00" risks the
    # ":00" being mis-parsed as a second field delimiter in `created_at:>=…`,
    # silently shifting or emptying the day's revenue/order KPIs.
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return day_start_utc.strftime(fmt), day_end_utc.strftime(fmt)


def _to_decimal(amount: str | None) -> Decimal | None:
    if amount is None:
        return None
    try:
        return Decimal(amount)
    except InvalidOperation:
        # A malformed money amount used to vanish here with zero trace: the
        # revenue loop below just skips it (silently under-totalling) and
        # _parse_order renders it as "$0.00" (silently wrong), both
        # indistinguishable from a legitimately free order. Log so a
        # Shopify wire-format change or a corrupt order shows up in Render
        # logs instead of only as an unexplained revenue discrepancy.
        _log.warning("Shopify order amount failed to parse as Decimal: %r", amount)
        return None


def _quantize(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_dashboard(raw: dict, currency_code: str) -> ShopifyDashboard:
    partial_failures = list(raw.get("partial_failures") or [])

    orders_nodes = raw.get("orders") or []
    page_limit = raw.get("orders_page_limit") or ORDERS_TRUNCATION_LIMIT
    truncated = bool(raw.get("orders_has_next_page")) or len(orders_nodes) >= page_limit

    revenue_amount: str | None = None
    if not truncated:
        total = Decimal("0")
        revenue_has_unparsed_order = False
        for node in orders_nodes:
            money = ((node.get("currentTotalPriceSet") or {}).get("shopMoney")) or {}
            dec = _to_decimal(money.get("amount"))
            if dec is not None:
                total += dec
            else:
                revenue_has_unparsed_order = True
        revenue_amount = _quantize(total)
        # _to_decimal already logs the raw cause; this surfaces the same
        # fact to the API response so the frontend can flag the KPI as
        # partial instead of presenting an under-totalled figure as exact.
        if revenue_has_unparsed_order and "revenue_amount" not in partial_failures:
            partial_failures.append("revenue_amount")

    order_count = raw.get("orders_count")
    order_count_approximate = raw.get("orders_count_precision") not in (
        None,
        "EXACT",
    )

    average_order_value: str | None = None
    if revenue_amount is not None and order_count:
        try:
            average_order_value = _quantize(
                Decimal(revenue_amount) / Decimal(order_count)
            )
        except (InvalidOperation, ZeroDivisionError):
            average_order_value = None

    recent_orders = [_parse_order(node) for node in orders_nodes[:RECENT_ORDERS_LIMIT]]

    # A failed productVariants alias yields an empty edge list, which
    # _count_low_stock would turn into a confident "0 low-stock SKUs" —
    # indistinguishable from a healthy, fully-stocked store. A truncated
    # first-page fetch would silently undercount for the same reason. Both
    # report None, which the UI renders as "—".
    variants_incomplete = "productVariants" in partial_failures or bool(
        raw.get("variants_has_next_page")
    )
    low_stock_sku_count = (
        None
        if variants_incomplete
        else _count_low_stock(raw.get("variants") or [], LOW_STOCK_DEFAULT_THRESHOLD)
    )

    return ShopifyDashboard(
        connected=True,
        needs_reauth=False,
        currency_code=currency_code,
        revenue_amount=revenue_amount,
        order_count=order_count,
        order_count_approximate=order_count_approximate,
        truncated=truncated,
        conversion_rate=None,
        conversion_rate_status="unavailable",
        average_order_value=average_order_value,
        low_stock_sku_count=low_stock_sku_count,
        low_stock_threshold=LOW_STOCK_DEFAULT_THRESHOLD,
        recent_orders=recent_orders,
        partial_failures=partial_failures,
    )


def _parse_order(node: dict) -> ShopifyOrder:
    money = ((node.get("currentTotalPriceSet") or {}).get("shopMoney")) or {}
    dec = _to_decimal(money.get("amount"))
    customer = node.get("customer") or {}
    return ShopifyOrder(
        id=str(node.get("id") or ""),
        order_number=str(node.get("name") or ""),
        customer_name=customer.get("displayName"),
        item_count=int((node.get("lineItems") or {}).get("totalCount") or 0),
        total_amount=_quantize(dec) if dec is not None else "0.00",
        currency_code=str(money.get("currencyCode") or ""),
        created_at=str(node.get("createdAt") or ""),
    )


def _count_low_stock(variants: list[dict], threshold: int) -> int:
    count = 0
    for node in variants:
        item = node.get("inventoryItem") or {}
        if not item.get("tracked"):
            continue
        available = 0
        for edge in (item.get("inventoryLevels") or {}).get("edges") or []:
            level = edge.get("node") or {}
            for q in level.get("quantities") or []:
                if q.get("name") == "available":
                    available += int(q.get("quantity") or 0)
        if available < threshold:
            count += 1
    return count


# ── Insights (FEAT-159) ──────────────────────────────────────────────────
#
# Revenue definition here is inherited from parse_dashboard's docstring
# above: gross, submitted, non-test orders (the same `test:false` filter),
# NOT net of refunds/discounts. Does not reconcile with Shopify Analytics.

# A period-over-period comparison needs each half to be more than a couple
# of points wide or the percentage is noise, not a trend.
_MIN_HALF_DAYS = 3


@dataclass(frozen=True)
class WindowBounds:
    """The shop-local calendar window an insights request covers.

    The ONE definition of "what days are in this window" — computed once
    in the router and threaded through client.execute_insights_query (as
    start_iso/end_iso) and parsers.parse_insights (as local_dates), so the
    window is never re-derived a second time from a timedelta division
    (which would be wrong across a DST transition).
    """

    start_iso: str
    end_iso: str
    local_dates: list[str]
    zone: ZoneInfo


def window_bounds(tz: str, now: datetime, days: int) -> WindowBounds:
    """Shop-local midnight `days - 1` days ago, through `now`.

    local_dates is built by iterating local calendar days, never by
    dividing a timedelta — a spring-forward/fall-back transition inside
    the window must still yield exactly `days` dates.
    """
    zone = _shop_zone(tz)
    local_now = now.astimezone(zone)
    local_today: date = local_now.date()
    first_date = local_today - timedelta(days=days - 1)
    local_dates = [
        (first_date + timedelta(days=offset)).isoformat() for offset in range(days)
    ]

    start_local_midnight = datetime.combine(first_date, dt_time.min, tzinfo=zone)
    fmt = "%Y-%m-%dT%H:%M:%SZ"  # see day_window's docstring for why bare "Z"
    return WindowBounds(
        start_iso=start_local_midnight.astimezone(timezone.utc).strftime(fmt),
        end_iso=local_now.astimezone(timezone.utc).strftime(fmt),
        local_dates=local_dates,
        zone=zone,
    )


@dataclass(frozen=True)
class ShopifyInsightsCore:
    """The parsed, currency/timezone-agnostic half of an insights payload.

    insights.build_insights attaches the remaining ctx-derived fields
    (timezone, currency_code, days, start_date, end_date) — kept separate
    so this stays a pure function of (raw, bounds, currency_code).
    """

    points: list[ShopifyInsightPoint]
    summary: ShopifyInsightSummary | None
    truncated: bool
    covered_through: str | None
    partial_failures: list[str]


def _local_date(created_at: str | None, zone: ZoneInfo) -> str | None:
    if not created_at:
        return None
    try:
        return (
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            .astimezone(zone)
            .date()
            .isoformat()
        )
    except ValueError:
        return None


def parse_insights(
    raw: dict, bounds: WindowBounds, currency_code: str
) -> ShopifyInsightsCore:
    """Bucket a paginated order range into one point per shop-local day.

    Pure — no I/O. `raw` is client.execute_insights_query's return dict.

    TRUNCATION RULE: when raw["truncated"] is True, every local date from
    the local date of raw["covered_through"] onwards gets
    revenue_amount=None / order_count=None (rendered by the frontend as a
    no-data gap), never a fabricated "0.00" — a truncated fetch on a
    high-volume store must not look like a real revenue cliff. The
    boundary day itself is a gap, not a value: orders are fetched
    ascending, so the fetch stopped partway THROUGH that day and its
    total is knowably incomplete — reporting it as a real figure would
    render exactly the false cliff this rule exists to prevent. summary is
    None whenever truncated is True, since it cannot be computed over a
    genuinely unknown tail of the window.

    The final date in the window is always marked is_partial_day=True and
    is excluded from every summary statistic — "today" is still
    accumulating orders at request time.
    """
    partial_failures = list(raw.get("partial_failures") or [])
    truncated = bool(raw.get("truncated"))
    covered_through = raw.get("covered_through")
    covered_through_date = _local_date(covered_through, bounds.zone)

    totals: dict[str, Decimal] = {d: Decimal("0") for d in bounds.local_dates}
    counts: dict[str, int] = {d: 0 for d in bounds.local_dates}

    for node in raw.get("orders") or []:
        local_date = _local_date(node.get("createdAt"), bounds.zone)
        if local_date is None or local_date not in totals:
            continue
        money = ((node.get("currentTotalPriceSet") or {}).get("shopMoney")) or {}
        dec = _to_decimal(money.get("amount"))
        if dec is None:
            if "revenue_amount" not in partial_failures:
                partial_failures.append("revenue_amount")
            continue
        totals[local_date] += dec
        counts[local_date] += 1

    last_date = bounds.local_dates[-1]
    points: list[ShopifyInsightPoint] = []
    for d in bounds.local_dates:
        is_partial_day = d == last_date
        # A truncated fetch that covered nothing (covered_through_date is
        # None) makes every date a gap; otherwise the boundary day and
        # everything after it are gaps — the boundary day is only
        # partially fetched, so its total is incomplete, not real.
        no_data = truncated and (
            covered_through_date is None or d >= covered_through_date
        )
        points.append(
            ShopifyInsightPoint(
                date=d,
                revenue_amount=None if no_data else _quantize(totals[d]),
                order_count=None if no_data else counts[d],
                is_partial_day=is_partial_day,
            )
        )

    summary = None if truncated else _build_summary(points)

    return ShopifyInsightsCore(
        points=points,
        summary=summary,
        truncated=truncated,
        covered_through=covered_through,
        partial_failures=partial_failures,
    )


def _build_summary(points: list[ShopifyInsightPoint]) -> ShopifyInsightSummary | None:
    """Window totals + period-over-period trend over completed days only.

    "Completed" = not is_partial_day and not a no-data gap. Compares the
    MEAN daily revenue of the first half of completed days against the
    second half (equal-length halves; the middle day is dropped on an odd
    count rather than biased into either half). Needs at least
    _MIN_HALF_DAYS days per half or the comparison is not reported.
    """
    completed = [
        p for p in points if not p.is_partial_day and p.revenue_amount is not None
    ]
    if not completed:
        return None

    window_revenue = sum((Decimal(p.revenue_amount) for p in completed), Decimal("0"))
    window_order_count = sum(p.order_count or 0 for p in completed)

    average_order_value: str | None = None
    if window_order_count:
        try:
            average_order_value = _quantize(
                window_revenue / Decimal(window_order_count)
            )
        except (InvalidOperation, ZeroDivisionError):
            average_order_value = None

    best = max(completed, key=lambda p: Decimal(p.revenue_amount))
    worst = min(completed, key=lambda p: Decimal(p.revenue_amount))

    n = len(completed)
    half = n // 2
    prior_period_change_pct: float | None = None
    direction: str = "unknown"
    if half >= _MIN_HALF_DAYS:
        first_half = completed[:half]
        second_half = completed[-half:]
        mean_first = sum(Decimal(p.revenue_amount) for p in first_half) / half
        mean_second = sum(Decimal(p.revenue_amount) for p in second_half) / half
        if mean_first > 0:
            prior_period_change_pct = round(
                float((mean_second - mean_first) / mean_first) * 100, 1
            )
            if prior_period_change_pct > 5:
                direction = "up"
            elif prior_period_change_pct < -5:
                direction = "down"
            else:
                direction = "flat"

    return ShopifyInsightSummary(
        window_revenue=_quantize(window_revenue),
        window_order_count=window_order_count,
        average_order_value=average_order_value,
        best_day=best.date,
        worst_day=worst.date,
        completed_day_count=n,
        prior_period_change_pct=prior_period_change_pct,
        direction=direction,
    )
