"""Google Calendar integration — fetches and maps today's primary-calendar events.

Pure I/O adapter: owns no token logic. Raises httpx errors on upstream HTTP/transport
failure; the caller decides how to degrade. A single malformed event is skipped
(logged by id only) rather than poisoning the whole batch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_HTTP_TIMEOUT = 10.0


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: str
    duration: str
    calendar: str
    source: str


def _today_utc_bounds() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return _to_rfc3339_z(start), _to_rfc3339_z(end)


def _to_rfc3339_z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _format_duration(start_dt: datetime, end_dt: datetime) -> str:
    minutes = int((end_dt - start_dt).total_seconds() // 60)
    if minutes <= 0:
        return "0min"
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}min"
    if hours:
        return f"{hours}h"
    return f"{mins}min"


def _map_event(raw: dict) -> CalendarEvent:
    start_node = raw.get("start", {})
    end_node = raw.get("end", {})
    title = raw.get("summary", "(no title)")
    event_id = raw.get("id", "")

    if "date" in start_node or "dateTime" not in start_node:
        return CalendarEvent(
            id=event_id,
            title=title,
            start="00:00",
            duration="all day",
            calendar="work",
            source="Google",
        )

    start_dt = _parse_iso(start_node["dateTime"])
    end_raw = end_node.get("dateTime")
    end_dt = _parse_iso(end_raw) if end_raw else start_dt
    return CalendarEvent(
        id=event_id,
        title=title,
        start=start_dt.strftime("%H:%M"),
        duration=_format_duration(start_dt, end_dt) if end_raw else "0min",
        calendar="work",
        source="Google",
    )


async def fetch_todays_events(access_token: str) -> list[CalendarEvent]:
    """Fetch today's events from the user's primary Google Calendar.

    Raises httpx errors on transport/HTTP failure (caller falls back entirely).
    A single unparseable event is skipped so one bad record cannot blank the list.
    """
    time_min, time_max = _today_utc_bounds()
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(CALENDAR_URL, headers=headers, params=params)
        resp.raise_for_status()
        payload = resp.json()

    events: list[CalendarEvent] = []
    for item in payload.get("items", []):
        try:
            events.append(_map_event(item))
        except (ValueError, KeyError, TypeError):
            logger.warning("Skipping unparseable calendar event id=%s", item.get("id"))
    return events
