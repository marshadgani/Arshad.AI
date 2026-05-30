"""calendar_list_events — fetch events between time_min and time_max."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import google_calendar
from ..registry import register


class ListEventsInput(BaseModel):
    time_min: str = Field(
        description="RFC3339 lower bound (inclusive), e.g. 2026-04-26T00:00:00Z"
    )
    time_max: str = Field(description="RFC3339 upper bound (exclusive)")
    max_results: int = Field(default=20, ge=1, le=250)
    calendar_id: str = Field(
        default="primary",
        description="Calendar ID; 'primary' for the user's main calendar",
    )


class EventSummary(BaseModel):
    id: str
    title: str | None
    start: str | None
    end: str | None
    location: str | None = None
    attendees: list[str] = Field(default_factory=list)
    html_link: str | None = None


class ListEventsOutput(BaseModel):
    data: dict[str, Any]
    summary: list[EventSummary]


def _summarize(item: dict[str, Any]) -> EventSummary:
    return EventSummary(
        id=item["id"],
        title=item.get("summary"),
        start=(item.get("start") or {}).get("dateTime")
        or (item.get("start") or {}).get("date"),
        end=(item.get("end") or {}).get("dateTime")
        or (item.get("end") or {}).get("date"),
        location=item.get("location"),
        attendees=[a.get("email", "") for a in item.get("attendees") or []],
        html_link=item.get("htmlLink"),
    )


@register
class CalendarListEvents(Tool):
    name = "calendar_list_events"
    description = (
        "List Google Calendar events between two RFC3339 timestamps on the user's "
        "primary (or specified) calendar. Returns up to max_results events ordered "
        "by start time."
    )
    input_schema = ListEventsInput
    output_schema = ListEventsOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ListEventsOutput:
        assert isinstance(payload, ListEventsInput)
        data = await google_calendar.request(
            db=db,
            user=user,
            method="GET",
            path=f"/calendars/{payload.calendar_id}/events",
            params={
                "timeMin": payload.time_min,
                "timeMax": payload.time_max,
                "maxResults": payload.max_results,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        return ListEventsOutput(
            data=data or {}, summary=[_summarize(it) for it in items]
        )
