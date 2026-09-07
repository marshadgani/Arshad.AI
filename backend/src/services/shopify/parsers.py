"""Wire-to-schema parsing for the Shopify dashboard. Pure functions, no I/O.

Revenue KPI definition (documented here because it drives every choice
below): gross revenue from submitted, non-test orders placed in the shop's
current calendar day (shop timezone). Does NOT exclude refunds or
discounts — it will not reconcile with Shopify Analytics, which nets those
post-order. The UI labels the figure accordingly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...schemas.shopify import ShopifyDashboard, ShopifyOrder

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


def day_window(tz: str, now: datetime) -> tuple[str, str]:
    """Local midnight -> now, in the shop's IANA timezone, as UTC ISO-8601
    bounds. Falls back to UTC for an unrecognised timezone rather than
    raising — a bad stored value must not blank the dashboard.
    """
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        # Silent by design (a bad stored value must not blank the
        # dashboard), but "silent to the user" must not mean "silent to
        # the operator" — without this, a corrupted shop_timezone value
        # quietly shifts every "today" boundary with nothing in the logs
        # to explain why revenue/order-count look off.
        _log.warning("Unrecognised Shopify shop timezone %r — falling back to UTC", tz)
        zone = ZoneInfo("UTC")
    local_now = now.astimezone(zone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_utc = local_midnight.astimezone(timezone.utc)
    day_end_utc = local_now.astimezone(timezone.utc)
    return day_start_utc.isoformat(), day_end_utc.isoformat()


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
