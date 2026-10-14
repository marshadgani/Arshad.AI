"""Trip-feasibility verdict. Pure: no I/O, no clock.

`as_of` and the window dates are injected so results are reproducible in
tests. The route fetches Shopify and Calendar data and hands it in here.

Verdict rule: any stockout projected on or before the end of the window plus
lookahead (so a variant that is already out of stock, or will run out before
the trip, counts: it will still be out of stock during the trip), or any timed
(non-all-day) event overlapping the window, is a conflict -> "no-go". With no
conflict, a source that failed, was not connected, needs reauth, or was
truncated -> "unknown" (a clean "go" is never produced from partial data).
Otherwise "go". A conflict found in healthy data is real even when another
source is degraded, so it still yields "no-go"; the degradation flags are
returned alongside so the caller can show both.

Timezone: window days are interpreted as UTC calendar days (UTC-midnight
bounds). The shop timezone is not available to Calendar-only users, so this is
a known approximation: a timed event within a few hours of a window edge can
be reported or missed depending on the user's UTC offset (for UTC+3, a 01:00
local event on the first day falls before the window).

Calendly is a required live source, like Calendar: not connected, needs reauth,
a failed read or a truncated read all force "unknown". One request reads at
most 100 scheduled events (the Calendly per-request cap); a response at the cap
sets `calendly_truncated` and forces "unknown" because an unexamined meeting
could be a conflict. Only an event's name, start, end and status are read, never
invitee data.

`calendar_truncated` forces "unknown" here, whereas build_inventory_cover's
route treats it as cacheable. The asymmetry is intentional: a capped calendar
cannot confirm conflict-free travel.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from ...schemas.shopify import (
    EVENT_TITLE_MAX,
    TripAllDayEvent,
    TripConflict,
    TripFeasibilityResponse,
    UnavailableSource,
)
from .inventory_cover import (
    available_quantity,
    project_stockout_date,
    units_sold_by_variant,
)
from .providers import CalendarResult

TRIP_STOCKOUT_LOOKAHEAD_DAYS = 7

# Always reported, never detected: these sources have no backend integration yet,
# so every response lists them as not connected rather than guessing a value.
UNAVAILABLE_SOURCE_NAMES = ("booking_com_pricing",)

INFRA_STALENESS_HOURS = 24
INFRA_FAILED_DEPLOY_STATUSES = frozenset(
    {"build_failed", "update_failed", "pre_deploy_failed"}
)
# A deploy status that is neither failed nor in this set is unknown to us and
# makes the Render source unreadable. "canceled" is a deliberate stop that leaves
# the previous deploy serving, so it is not an outage.
INFRA_HEALTHY_DEPLOY_STATUSES = frozenset(
    {
        "live",
        "created",
        "build_in_progress",
        "update_in_progress",
        "pre_deploy_in_progress",
        "deactivated",
        "canceled",
    }
)
INFRA_HEALTHY_PROJECT_STATUS = "ACTIVE_HEALTHY"


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_instant(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _stockout_conflicts(
    variants_data: dict[str, Any],
    orders_data: dict[str, Any],
    *,
    as_of: datetime,
    window_days: int,
    last_day: date,
) -> tuple[list[TripConflict], bool]:
    """(stockout conflicts, any tracked variant had no readable stock level).

    A tracked variant with no 'available' level cannot be projected, so it is
    reported rather than silently skipped: a clean "go" must not rest on
    variants that were never checked.
    """
    sold = units_sold_by_variant(orders_data.get("orders") or [])
    found: list[tuple[date, TripConflict]] = []
    unreadable = False
    for node in variants_data.get("variants") or []:
        inv = node.get("inventoryItem")
        if not isinstance(inv, dict) or "tracked" not in inv:
            # Unknown (a scope gap can null inventoryItem), not "untracked".
            unreadable = True
            continue
        if not inv.get("tracked"):
            continue
        available = available_quantity(inv)
        if available is None:
            unreadable = True
            continue
        variant_id = str(node.get("id"))
        stockout = project_stockout_date(
            available, sold.get(variant_id, 0), as_of=as_of, window_days=window_days
        )
        if stockout is not None and stockout <= last_day:
            found.append(
                (
                    stockout,
                    TripConflict(
                        type="stockout",
                        variant_id=variant_id[:255],
                        projected_stockout_date=stockout.isoformat(),
                    ),
                )
            )
    found.sort(key=lambda pair: (pair[0], pair[1].variant_id or ""))
    return [conflict for _, conflict in found], unreadable


def _calendar_findings(
    events: list[Any], start_date: date, end_date: date
) -> tuple[list[TripConflict], list[TripAllDayEvent], bool]:
    """(timed conflicts, all-day events listed, any event unreadable)."""
    win_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    win_end = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    timed: list[tuple[datetime, TripConflict]] = []
    all_day: list[TripAllDayEvent] = []
    unreadable = False
    for event in events:
        if not isinstance(event, dict):
            unreadable = True
            continue
        if event.get("status") == "cancelled":
            continue
        title = str(event.get("summary") or "(no title)")[:EVENT_TITLE_MAX]
        start = event.get("start") if isinstance(event.get("start"), dict) else {}
        end = event.get("end") if isinstance(event.get("end"), dict) else {}
        if start.get("dateTime"):
            begin = _parse_instant(start["dateTime"])
            finish = (
                _parse_instant(end.get("dateTime")) if end.get("dateTime") else None
            )
            if begin is None or finish is None:
                unreadable = True
                continue
            if begin < win_end and finish > win_start:
                timed.append(
                    (
                        begin,
                        TripConflict(
                            type="calendar_event",
                            event_title=title,
                            event_start=str(start["dateTime"])[:64],
                            event_end=str(end["dateTime"])[:64],
                        ),
                    )
                )
        elif start.get("date"):
            first = _parse_date(start["date"])
            if first is None:
                unreadable = True
                continue
            # end.date is exclusive in the Google Calendar API;
            # a missing end means a single day.
            last_exclusive = (
                _parse_date(end["date"])
                if end.get("date")
                else first + timedelta(days=1)
            )
            if last_exclusive is None or last_exclusive <= first:
                unreadable = True
                continue
            if first <= end_date and last_exclusive > start_date:
                all_day.append(
                    TripAllDayEvent(title=title, start_date=first.isoformat())
                )
        else:
            unreadable = True
    timed.sort(key=lambda pair: pair[0])
    return [c for _, c in timed], all_day, unreadable


def _calendly_findings(
    events: list[Any], start_date: date, end_date: date
) -> tuple[list[TripConflict], bool]:
    """(meeting conflicts, any event unreadable). Calendly titles are `name`
    (Google's is `summary`). Reads name/start_time/end_time/status only."""
    win_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    win_end = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    found: list[tuple[datetime, TripConflict]] = []
    unreadable = False
    for event in events:
        if not isinstance(event, dict):
            unreadable = True
            continue
        if event.get("status") != "active":
            continue
        begin = _parse_instant(event.get("start_time"))
        finish = _parse_instant(event.get("end_time"))
        if begin is None or finish is None:
            unreadable = True
            continue
        if begin < win_end and finish > win_start:
            found.append(
                (
                    begin,
                    TripConflict(
                        type="calendly_event",
                        calendly_event_title=str(event.get("name") or "(no title)")[
                            :EVENT_TITLE_MAX
                        ],
                        calendly_event_start=str(event["start_time"])[:64],
                        calendly_event_end=str(event["end_time"])[:64],
                    ),
                )
            )
    found.sort(key=lambda pair: pair[0])
    return [c for _, c in found], unreadable


def _snapshot_flags(
    config: dict[str, Any] | None, status: str | None, as_of: datetime
) -> dict[str, bool]:
    """Connection and freshness flags for one infrastructure snapshot.

    A missing, unparseable or future `synced_at` means never synced: it is
    never read as fresh.
    """
    if config is None:
        return {
            "connected": False,
            "needs_sync": False,
            "stale": False,
            "sync_error": False,
        }
    raw = config.get("synced_at")
    synced = _parse_instant(raw) if raw else None
    needs_sync = synced is None or synced > as_of
    stale = not needs_sync and as_of - synced > timedelta(hours=INFRA_STALENESS_HOURS)
    return {
        "connected": True,
        "needs_sync": needs_sync,
        "stale": stale,
        "sync_error": status != "connected",
    }


def _infra_conflict(provider: str, name: Any, state: str) -> TripConflict:
    return TripConflict(
        type="infrastructure",
        provider=provider,
        infra_name=str(name or "(unnamed)")[:255],
        infra_state=state[:64],
    )


def _infrastructure_findings(
    render_config: dict[str, Any] | None,
    supabase_config: dict[str, Any] | None,
    render_status: str | None,
    supabase_status: str | None,
    *,
    as_of: datetime,
) -> tuple[list[TripConflict], dict[str, bool], list[str]]:
    """(conflicts, per-provider flags, unreadable-health labels). Pure: reads
    the last synced snapshots only.

    Conflicts come from whatever snapshot exists, even a stale one: a service
    seen suspended is still worth reporting. Staleness, never-synced and
    sync-error only degrade (verdict "unknown"), they never invent a conflict.
    A missing or malformed list, entry, suspended state, deploy status or
    project status is reported as `<provider>_health` in the third value: it
    degrades the verdict, so unreadable data can never be read as healthy.
    """
    render = _snapshot_flags(render_config, render_status, as_of)
    supabase = _snapshot_flags(supabase_config, supabase_status, as_of)
    conflicts: list[TripConflict] = []
    render_unreadable = False
    supabase_unreadable = False

    if render_config is not None:
        services = render_config.get("services")
        if not isinstance(services, list):
            render_unreadable = True
            services = []
        for svc in services:
            if not isinstance(svc, dict):
                render_unreadable = True
                continue
            deploy = svc.get("latest_deploy_status")
            suspended = svc.get("suspended")
            if suspended == "suspended":
                conflicts.append(
                    _infra_conflict("render", svc.get("name"), "suspended")
                )
            elif isinstance(deploy, str) and deploy in INFRA_FAILED_DEPLOY_STATUSES:
                conflicts.append(_infra_conflict("render", svc.get("name"), deploy))
            elif deploy is not None and (
                not isinstance(deploy, str)
                or deploy not in INFRA_HEALTHY_DEPLOY_STATUSES
            ):
                # "unchecked", an unrecognised status, or a bad value: unknown.
                render_unreadable = True
            elif suspended != "not_suspended":
                # Unknown suspended state: cannot determine service health.
                # Note: suspended="not_suspended" with deploy=None means the
                # service exists but has never been deployed — this is healthy,
                # not unreadable.
                render_unreadable = True

    if supabase_config is not None:
        projects = supabase_config.get("projects")
        if not isinstance(projects, list):
            supabase_unreadable = True
            projects = []
        for proj in projects:
            state = proj.get("status") if isinstance(proj, dict) else None
            if not isinstance(state, str) or not state:
                supabase_unreadable = True
            elif state != INFRA_HEALTHY_PROJECT_STATUS:
                conflicts.append(_infra_conflict("supabase", proj.get("name"), state))

    flags = {
        "render_connected": render["connected"],
        "render_needs_sync": render["needs_sync"],
        "render_stale": render["stale"],
        "render_sync_error": render["sync_error"],
        "render_truncated": bool(
            render_config and render_config.get("services_truncated") is True
        ),
        "supabase_connected": supabase["connected"],
        "supabase_needs_sync": supabase["needs_sync"],
        "supabase_stale": supabase["stale"],
        "supabase_sync_error": supabase["sync_error"],
    }
    unreadable = []
    if render_unreadable:
        unreadable.append("render_health")
    if supabase_unreadable:
        unreadable.append("supabase_health")
    return conflicts, flags, unreadable


def _truncation_flags(
    variants_data: dict[str, Any] | None,
    orders_data: dict[str, Any] | None,
) -> tuple[bool, bool]:
    """Return (variants_truncated, orders_truncated) from raw fetch payloads."""
    variants_truncated = bool(
        variants_data and variants_data.get("variants_has_next_page")
    )
    orders_truncated = bool(
        orders_data
        and (
            orders_data.get("orders_has_next_page")
            or orders_data.get("line_items_truncated")
        )
    )
    return variants_truncated, orders_truncated


def _determine_verdict(
    conflicts: list[TripConflict],
    *,
    degraded: bool,
) -> str:
    """Map conflicts + degradation state to the wire verdict string.

    Deliberate deviation from the original spec, which said any degraded source
    gives "unknown": a conflict actually found in healthy data stays "no-go".
    Hiding it behind "unknown" because an unrelated source failed would be the
    less cautious answer. "go" is returned only when nothing conflicts and
    nothing was degraded.
    """
    if conflicts:
        return "no-go"
    if degraded:
        return "unknown"
    return "go"


def _compute_infra_degraded(infra: dict[str, bool]) -> bool:
    """True when a connected infrastructure source has an unresolved sync issue.

    Mirrors the degradation check in TripFeasibilityResponse._check_verdict_invariants
    so the two stay in sync and neither hides a stale or unsynchronised source.
    """
    return (
        infra["render_connected"]
        and (
            infra["render_needs_sync"]
            or infra["render_stale"]
            or infra["render_sync_error"]
            or infra["render_truncated"]
        )
    ) or (
        infra["supabase_connected"]
        and (
            infra["supabase_needs_sync"]
            or infra["supabase_stale"]
            or infra["supabase_sync_error"]
        )
    )


def check_trip_feasibility(
    *,
    as_of: datetime,
    start_date: date,
    end_date: date,
    variants_data: dict[str, Any] | None,
    orders_data: dict[str, Any] | None,
    cal: CalendarResult,
    shopify_connected: bool,
    shopify_needs_reauth: bool,
    window_days: int,
    partial_failures: list[str],
    render_config: dict[str, Any] | None = None,
    supabase_config: dict[str, Any] | None = None,
    render_status: str | None = None,
    supabase_status: str | None = None,
    calendly_events: list[Any] | None = None,
    calendly_connected: bool = False,
    calendly_needs_reauth: bool = False,
    calendly_truncated: bool = False,
    calendly_partial_failure: bool = False,
) -> TripFeasibilityResponse:
    """Assemble the verdict from already-fetched data.

    `variants_data` / `orders_data` are None when that fetch failed (or Shopify
    was unavailable); `partial_failures` carries the route's failure labels.
    """
    shopify_usable = shopify_connected and not shopify_needs_reauth
    variants_truncated, orders_truncated = _truncation_flags(variants_data, orders_data)

    conflicts: list[TripConflict] = []
    levels_unreadable = False
    if shopify_usable and variants_data is not None and orders_data is not None:
        stockouts, levels_unreadable = _stockout_conflicts(
            variants_data,
            orders_data,
            as_of=as_of,
            window_days=window_days,
            last_day=end_date + timedelta(days=TRIP_STOCKOUT_LOOKAHEAD_DAYS),
        )
        conflicts.extend(stockouts)

    all_day: list[TripAllDayEvent] = []
    calendar_unreadable = False
    calendar_usable = cal.connected and not cal.needs_reauth
    if calendar_usable:
        timed, all_day, calendar_unreadable = _calendar_findings(
            cal.events, start_date, end_date
        )
        conflicts.extend(timed)

    calendly_unreadable = False
    calendly_usable = calendly_connected and not calendly_needs_reauth
    if calendly_usable and calendly_events:
        meetings, calendly_unreadable = _calendly_findings(
            calendly_events, start_date, end_date
        )
        conflicts.extend(meetings)

    infra_conflicts, infra, infra_unreadable = _infrastructure_findings(
        render_config,
        supabase_config,
        render_status,
        supabase_status,
        as_of=as_of,
    )
    conflicts.extend(infra_conflicts)
    infra_degraded = _compute_infra_degraded(infra)

    failures = list(dict.fromkeys([*partial_failures, *cal.partial_failures]))
    if calendar_unreadable and "calendar" not in failures:
        failures.append("calendar")
    if levels_unreadable and "inventory_levels" not in failures:
        failures.append("inventory_levels")
    if (calendly_partial_failure or calendly_unreadable) and (
        "calendly" not in failures
    ):
        failures.append("calendly")
    if calendly_truncated and "calendly_truncated" not in failures:
        failures.append("calendly_truncated")
    failures.extend(f for f in infra_unreadable if f not in failures)

    degraded = (
        not shopify_usable
        or not calendar_usable
        or not calendly_usable
        or calendly_truncated
        or variants_data is None
        or orders_data is None
        or variants_truncated
        or orders_truncated
        or cal.calendar_truncated
        or bool(failures)
        or infra_degraded
    )
    verdict = _determine_verdict(conflicts, degraded=degraded)

    unavail = list(UNAVAILABLE_SOURCE_NAMES)
    if not infra["render_connected"]:
        unavail.append("render_health")
    if not infra["supabase_connected"]:
        unavail.append("supabase_health")

    return TripFeasibilityResponse(
        verdict=verdict,
        conflicts=conflicts,
        all_day_events=all_day,
        unavailable_sources=[UnavailableSource(name=n) for n in unavail],
        shopify_connected=shopify_connected,
        shopify_needs_reauth=shopify_needs_reauth,
        calendar_connected=cal.connected,
        calendar_needs_reauth=cal.needs_reauth,
        variants_truncated=variants_truncated,
        orders_truncated=orders_truncated,
        calendar_truncated=cal.calendar_truncated,
        calendly_connected=calendly_connected,
        calendly_needs_reauth=calendly_needs_reauth,
        calendly_truncated=calendly_truncated,
        partial_failures=failures,
        **infra,
    )
