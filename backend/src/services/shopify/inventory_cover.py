"""Days-of-cover and travel-window stockout alerts. Pure: no I/O, no clock.

`as_of` is injected by the route so projections are reproducible in tests.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from ...schemas.shopify import DaysCoverItem, InventoryCoverResponse, StockoutAlert

_TENTH = Decimal("0.1")


def _fmt(value: Decimal) -> str:
    return str(value.quantize(_TENTH, rounding=ROUND_HALF_UP))


def _available(item: dict[str, Any]) -> int | None:
    """Summed 'available' across locations; None if Shopify reported no level."""
    total: int | None = None
    for edge in (item.get("inventoryLevels") or {}).get("edges") or []:
        for q in ((edge.get("node") or {}).get("quantities")) or []:
            if q.get("name") == "available":
                total = (total or 0) + int(q.get("quantity") or 0)
    return total


def _units_sold(orders: list[dict[str, Any]]) -> dict[str, int]:
    sold: dict[str, int] = defaultdict(int)
    for order in orders:
        for edge in (order.get("lineItems") or {}).get("edges") or []:
            node = edge.get("node") or {}
            variant_id = (node.get("variant") or {}).get("id")
            if variant_id:
                sold[variant_id] += int(node.get("quantity") or 0)
    return sold


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def travel_windows(events: list[dict[str, Any]]) -> list[tuple[date, date, str]]:
    """(first day, exclusive end day, title) for each multi-day all-day event."""
    windows: list[tuple[date, date, str]] = []
    for event in events:
        if event.get("status") == "cancelled":
            continue
        start = _parse_day((event.get("start") or {}).get("date"))
        end = _parse_day((event.get("end") or {}).get("date"))
        if start is None or end is None:
            continue  # timed events carry start.dateTime, not start.date
        # end.date is exclusive in the Google Calendar API: Monday-Tuesday is
        # start=Mon, end=Wed, so .days == 2 and "> 1" means "spans more than
        # one day". A single all-day event has end = start + 1 day.
        if (end - start).days > 1:
            windows.append((start, end, event.get("summary") or "(no title)"))
    return windows


def build_inventory_cover(
    variants_data: dict[str, Any] | None,
    orders_data: dict[str, Any] | None,
    events: list[dict[str, Any]],
    *,
    as_of: datetime,
    window_days: int,
    calendar_connected: bool,
    calendar_needs_reauth: bool,
    partial_failures: list[str],
) -> InventoryCoverResponse:
    # None means the fetch failed: velocity is unknown, which must not be
    # reported as "no recent sales".
    variants_data = variants_data or {}
    velocity_known = orders_data is not None
    orders_data = orders_data or {}
    sold = _units_sold(orders_data.get("orders") or [])
    windows = travel_windows(events) if calendar_connected else []
    window = Decimal(window_days)

    items: list[DaysCoverItem] = []
    alerts: list[StockoutAlert] = []
    for node in variants_data.get("variants") or []:
        inv = node.get("inventoryItem") or {}
        if not inv.get("tracked"):
            continue
        available = _available(inv)
        if available is None:
            continue
        variant_id = str(node.get("id"))
        units = sold.get(variant_id, 0)
        if not velocity_known:
            items.append(DaysCoverItem(variant_id=variant_id, available_qty=available))
            continue
        if units <= 0:
            items.append(
                DaysCoverItem(
                    variant_id=variant_id, available_qty=available, no_recent_sales=True
                )
            )
            continue

        velocity = Decimal(units) / window
        cover = Decimal(max(available, 0)) / velocity
        stockout = as_of.date() + timedelta(
            days=int(cover.to_integral_value(rounding=ROUND_FLOOR))
        )
        hit = next((w for w in windows if w[0] <= stockout < w[1]), None)
        items.append(
            DaysCoverItem(
                variant_id=variant_id,
                available_qty=available,
                velocity_30d=_fmt(velocity),
                days_of_cover=_fmt(cover),
                is_alert=hit is not None,
                projected_stockout_date=stockout.isoformat() if hit else None,
            )
        )
        if hit:
            alerts.append(
                StockoutAlert(
                    variant_id=variant_id,
                    projected_stockout_date=stockout.isoformat(),
                    travel_event_title=hit[2],
                )
            )

    # Lowest cover first; no-sales rows last.
    items.sort(key=lambda i: (i.days_of_cover is None, Decimal(i.days_of_cover or 0)))
    alerts.sort(key=lambda a: a.projected_stockout_date)
    return InventoryCoverResponse(
        connected=True,
        days_of_cover=items,
        alerts=alerts,
        variants_truncated=bool(variants_data.get("variants_has_next_page")),
        orders_truncated=bool(
            orders_data.get("orders_has_next_page")
            or orders_data.get("line_items_truncated")
        ),
        calendar_connected=calendar_connected,
        calendar_needs_reauth=calendar_needs_reauth,
        partial_failures=partial_failures,
    )
