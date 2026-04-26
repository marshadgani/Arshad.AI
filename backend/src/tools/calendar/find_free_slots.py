"""calendar_find_free_slots — derive free windows from Google's freeBusy.

Uses ``/freeBusy`` to fetch busy ranges across one or more calendars,
then walks the [time_min, time_max] window subtracting busy intervals to
produce free slots of at least ``duration_minutes``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool, ToolError
from ..clients import google_calendar
from ..registry import register


class FindFreeSlotsInput(BaseModel):
    time_min: str = Field(description="RFC3339 start of the search window")
    time_max: str = Field(description="RFC3339 end of the search window")
    duration_minutes: int = Field(ge=5, le=24 * 60)
    max_results: int = Field(default=5, ge=1, le=50)
    calendar_ids: list[str] = Field(
        default_factory=lambda: ["primary"],
        description="Calendars whose busy ranges block free slots",
    )


class FreeSlot(BaseModel):
    start: str
    end: str


class FindFreeSlotsOutput(BaseModel):
    data: dict[str, Any]
    summary: list[FreeSlot]


def _parse(rfc3339: str) -> datetime:
    # Google freeBusy returns 'Z'-suffixed UTC; fromisoformat in 3.12 handles 'Z'.
    return datetime.fromisoformat(rfc3339.replace("Z", "+00:00"))


@register
class CalendarFindFreeSlots(Tool):
    name = "calendar_find_free_slots"
    description = (
        "Find free time slots of at least duration_minutes in the [time_min, time_max] "
        "window across the user's specified calendars. Returns up to max_results slots "
        "in chronological order."
    )
    input_schema = FindFreeSlotsInput
    output_schema = FindFreeSlotsOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> FindFreeSlotsOutput:
        assert isinstance(payload, FindFreeSlotsInput)
        data = await google_calendar.request(
            db=db,
            user=user,
            method="POST",
            path="/freeBusy",
            json={
                "timeMin": payload.time_min,
                "timeMax": payload.time_max,
                "items": [{"id": cid} for cid in payload.calendar_ids],
            },
        )
        if not isinstance(data, dict):
            raise ToolError(
                "provider_unexpected_response", "freeBusy returned non-object"
            )

        # Merge busy ranges across all calendars, then sort by start.
        busy: list[tuple[datetime, datetime]] = []
        for cid in payload.calendar_ids:
            ranges = (data.get("calendars") or {}).get(cid, {}).get("busy", [])
            for r in ranges:
                busy.append((_parse(r["start"]), _parse(r["end"])))
        busy.sort()

        # Walk free intervals, splitting on each busy range.
        cursor = _parse(payload.time_min)
        end = _parse(payload.time_max)
        duration = timedelta(minutes=payload.duration_minutes)
        slots: list[FreeSlot] = []

        for b_start, b_end in busy:
            if cursor + duration <= b_start:
                slots.append(
                    FreeSlot(start=cursor.isoformat(), end=b_start.isoformat())
                )
                if len(slots) >= payload.max_results:
                    break
            if b_end > cursor:
                cursor = b_end

        if len(slots) < payload.max_results and cursor + duration <= end:
            slots.append(FreeSlot(start=cursor.isoformat(), end=end.isoformat()))

        return FindFreeSlotsOutput(data=data, summary=slots[: payload.max_results])
