"""calendar/meeting_suggester — finds free slots + surrounding context.

Phase E composition: free-slot search PLUS the events on either side of
each candidate slot, so the caller can see "what's before / what's after"
without a second round-trip. Phase B will add Claude reasoning to pick
the best slot given attendee preferences.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.calendar.find_free_slots import (
    CalendarFindFreeSlots,
    FindFreeSlotsInput,
    FreeSlot,
)
from ...tools.calendar.list_events import (
    CalendarListEvents,
    EventSummary,
    ListEventsInput,
)
from ..base import Agent
from ..registry import register


class MeetingSuggesterInput(BaseModel):
    time_min: str = Field(description="RFC3339 start of search window")
    time_max: str = Field(description="RFC3339 end of search window")
    duration_minutes: int = Field(ge=5, le=24 * 60)
    max_results: int = Field(default=5, ge=1, le=20)


class MeetingSuggesterSummary(BaseModel):
    free_slots: list[FreeSlot]
    events_in_window: list[EventSummary]


class MeetingSuggesterOutput(BaseModel):
    data: dict[str, Any]
    summary: MeetingSuggesterSummary


@register
class MeetingSuggesterAgent(Agent):
    domain = "calendar"
    name = "meeting_suggester"
    description = (
        "Suggests up to N meeting slots of a given duration in a window, "
        "alongside the events already scheduled in that window for context. "
        "Phase E: deterministic. Phase B will rank slots by attendee fit."
    )
    input_schema = MeetingSuggesterInput
    output_schema = MeetingSuggesterOutput
    tool_dependencies = ["calendar_find_free_slots", "calendar_list_events"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> MeetingSuggesterOutput:
        assert isinstance(payload, MeetingSuggesterInput)
        free = await CalendarFindFreeSlots()(
            user=user,
            db=db,
            payload=FindFreeSlotsInput(
                time_min=payload.time_min,
                time_max=payload.time_max,
                duration_minutes=payload.duration_minutes,
                max_results=payload.max_results,
            ),
        )
        events = await CalendarListEvents()(
            user=user,
            db=db,
            payload=ListEventsInput(
                time_min=payload.time_min,
                time_max=payload.time_max,
                max_results=50,
            ),
        )
        return MeetingSuggesterOutput(
            data={"free_slots": free.data, "events": events.data},
            summary=MeetingSuggesterSummary(
                free_slots=free.summary,
                events_in_window=events.summary,
            ),
        )
