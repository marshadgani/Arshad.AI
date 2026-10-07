"""Calendar ingestion runner.

Pulls a window of events from the user's primary calendar via the Phase D
``calendar_list_events`` tool, upserts each into ``ingested_calendar_events``
keyed by (user_id, provider_id), publishes
``events.calendar.ingested`` with batch counts.

Window: by default the next 30 days. ``payload.full_refresh=true`` widens
to (now - 90d, now + 365d). ``payload.history_days=N`` reads from N days ago
(capped at 10 years) to now + 365d and follows Google's page links, so a long
history is not cut off at one batch; other runs read a single batch.
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
from .errors import IngestionError

_DEFAULT_LOOKAHEAD_DAYS = 30
_MAX_HISTORY_DAYS = 3650
_MAX_HISTORY_PAGES = 40


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
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            # start.date (all-day events) parses to a naive midnight;
            # occurred_at is TIMESTAMP WITH TIME ZONE, so a naive value
            # here raises the same asyncpg error FEAT-157 fixed elsewhere.
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _history_days(payload: dict[str, Any]) -> int | None:
    raw = payload.get("history_days")
    if raw is None:
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        raise IngestionError(f"invalid_history_days: {raw!r}") from None
    if days < 1:
        raise IngestionError(f"invalid_history_days: {raw!r}")
    return min(days, _MAX_HISTORY_DAYS)


async def ingest(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    full_refresh = bool(payload.get("full_refresh", False))
    history_days = _history_days(payload)
    now = datetime.now(timezone.utc)
    if history_days is not None:
        time_min = now - timedelta(days=history_days)
        time_max = now + timedelta(days=365)
    elif full_refresh:
        time_min = now - timedelta(days=90)
        time_max = now + timedelta(days=365)
    else:
        time_min = now
        time_max = now + timedelta(days=_DEFAULT_LOOKAHEAD_DAYS)

    items: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(_MAX_HISTORY_PAGES if history_days is not None else 1):
        result = await CalendarListEvents()(
            user=user,
            db=db,
            payload=ListEventsInput(
                time_min=time_min.isoformat(),
                time_max=time_max.isoformat(),
                max_results=_max_batch(),
                page_token=page_token,
            ),
        )
        data = result.data or {}
        items.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    if not items:
        await event_bus.publish(
            "events.calendar.ingested",
            {"user_id": str(user.id), "ingested_count": 0, "skipped_count": 0},
        )
        return {"ingested_count": 0, "skipped_count": 0}

    # One INSERT .. ON CONFLICT cannot touch the same row twice, so keep the
    # last copy of any id repeated across pages.
    by_id = {item["id"]: item for item in items if item.get("id")}
    rows = [
        {
            "user_id": user.id,
            "occurred_at": _parse_event_start(item),
            "provider_id": item_id,
            "raw": item,
        }
        for item_id, item in by_id.items()
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
