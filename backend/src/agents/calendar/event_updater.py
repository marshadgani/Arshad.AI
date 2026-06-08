"""calendar/event_updater — agent wrapper around calendar_update_event."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.calendar.update_event import (
    CalendarUpdateEvent,
    UpdateEventInput,
    UpdateEventSummary,
)
from ..base import Agent
from ..registry import register


class EventUpdaterOutput(BaseModel):
    data: dict[str, Any]
    summary: UpdateEventSummary


@register
class EventUpdaterAgent(Agent):
    domain = "calendar"
    name = "event_updater"
    description = (
        "Updates an existing Google Calendar event. Phase E: pass-through "
        "to calendar_update_event. Phase B will resolve event references "
        "from natural language ('move my 3pm to 4pm')."
    )
    input_schema = UpdateEventInput
    output_schema = EventUpdaterOutput
    tool_dependencies = ["calendar_update_event"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EventUpdaterOutput:
        result = await CalendarUpdateEvent()(user=user, db=db, payload=payload)
        return EventUpdaterOutput(data=result.data, summary=result.summary)
