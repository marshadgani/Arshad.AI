"""Calendar ingestion runner.

Pulls a window of events from the user's primary calendar via the Phase D
``calendar_list_events`` tool, upserts each into ``ingested_calendar_events``
keyed by (user_id, provider_id), publishes
``events.calendar.ingested`` with batch counts.

Window: by default the next 30 days. ``payload.full_refresh=true`` widens
to (now - 90d, now + 365d).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.ingested import IngestedCalendarEvent
from ...models.user import User
from ...tools.calendar.list_events import CalendarListEvents, ListEventsInput
from .. import event_bus

_DEFAULT_LOOKAHEAD_DAYS = 30


def _max_batch() -> int:
    try:
        return max(1, int(os.getenv("MAX_INGEST_BATCH_SIZE", "100")))
    except ValueError:
        return 100


def _parse_event_start(raw: dict[str, Any]) -> datetime:
    """Google Calendar emits start.dateTime (timed) or start.date (all-day).

    Falls back to now() if absent so cancelled events still land somewhere
    sane on occurred_at; raw is preserved verbatim for downstream queries.
    """
    start = raw.get("start") or {}
    value = start.get("dateTime") or start.get("date")
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


async def ingest(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    full_refresh = bool(payload.get("full_refresh", False))
    now = datetime.now(timezone.utc)
    if full_refresh:
        time_min = now - timedelta(days=90)
        time_max = now + timedelta(days=365)
    else:
        time_min = now
        time_max = now + timedelta(days=_DEFAULT_LOOKAHEAD_DAYS)

    result = await CalendarListEvents()(
        user=user,
        db=db,
        payload=ListEventsInput(
            time_min=time_min.isoformat(),
            time_max=time_max.isoformat(),
            max_results=_max_batch(),
        ),
    )
    items: list[dict[str, Any]] = (result.data or {}).get("items", [])

    if not items:
        await event_bus.publish(
            "events.calendar.ingested",
            {"user_id": str(user.id), "ingested_count": 0, "skipped_count": 0},
        )
        return {"ingested_count": 0, "skipped_count": 0}

    rows = [
        {
            "user_id": user.id,
            "occurred_at": _parse_event_start(item),
            "provider_id": item["id"],
            "raw": item,
        }
        for item in items
        if item.get("id")
    ]
    skipped = len(items) - len(rows)

    if rows:
        stmt = pg_insert(IngestedCalendarEvent).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "provider_id"],
            set_={
                "raw": stmt.excluded.raw,
                "occurred_at": stmt.excluded.occurred_at,
                "ingested_at": datetime.now(timezone.utc),
            },
        )
        await db.execute(stmt)
        await db.commit()

    await event_bus.publish(
        "events.calendar.ingested",
        {
            "user_id": str(user.id),
            "ingested_count": len(rows),
            "skipped_count": skipped,
        },
    )
    return {"ingested_count": len(rows), "skipped_count": skipped}
