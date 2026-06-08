"""calendar/event_creator — agent wrapper around calendar_create_event."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.calendar.create_event import (
    CalendarCreateEvent,
    CreateEventInput,
    CreateEventSummary,
)
from ..base import Agent
from ..registry import register


class EventCreatorOutput(BaseModel):
    data: dict[str, Any]
    summary: CreateEventSummary


@register
class EventCreatorAgent(Agent):
    domain = "calendar"
    name = "event_creator"
    description = (
        "Creates a Google Calendar event from structured input. "
        "Phase E: deterministic pass-through to calendar_create_event. "
        "Phase B will accept natural-language input and translate."
    )
    input_schema = CreateEventInput
    output_schema = EventCreatorOutput
    tool_dependencies = ["calendar_create_event"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EventCreatorOutput:
        result = await CalendarCreateEvent()(user=user, db=db, payload=payload)
        return EventCreatorOutput(data=result.data, summary=result.summary)
