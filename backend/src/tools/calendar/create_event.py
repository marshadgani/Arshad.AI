"""calendar_create_event — insert a new event on the user's calendar."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import google_calendar
from ..registry import register


class CreateEventInput(BaseModel):
    title: str = Field(min_length=1, max_length=1024)
    start: str = Field(description="RFC3339 start datetime")
    end: str = Field(description="RFC3339 end datetime")
    description: str | None = None
    location: str | None = None
    attendees: list[str] = Field(default_factory=list, description="Attendee emails")
    calendar_id: str = Field(default="primary")
    send_updates: str = Field(
        default="none",
        description="Whether to email attendees: 'all' | 'externalOnly' | 'none'",
    )


class CreateEventSummary(BaseModel):
    id: str
    title: str | None
    start: str | None
    end: str | None
    html_link: str | None


class CreateEventOutput(BaseModel):
    data: dict[str, Any]
    summary: CreateEventSummary


@register
class CalendarCreateEvent(Tool):
    name = "calendar_create_event"
    description = (
        "Create a new event on the user's Google Calendar. Times are RFC3339. "
        "send_updates controls whether attendees get an email invite."
    )
    input_schema = CreateEventInput
    output_schema = CreateEventOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CreateEventOutput:
        assert isinstance(payload, CreateEventInput)
        body: dict[str, Any] = {
            "summary": payload.title,
            "start": {"dateTime": payload.start},
            "end": {"dateTime": payload.end},
        }
        if payload.description:
            body["description"] = payload.description
        if payload.location:
            body["location"] = payload.location
        if payload.attendees:
            body["attendees"] = [{"email": e} for e in payload.attendees]

        data = await google_calendar.request(
            db=db,
            user=user,
            method="POST",
            path=f"/calendars/{payload.calendar_id}/events",
            params={"sendUpdates": payload.send_updates},
            json=body,
        )
        return CreateEventOutput(
            data=data or {},
            summary=CreateEventSummary(
                id=data["id"],
                title=data.get("summary"),
                start=(data.get("start") or {}).get("dateTime"),
                end=(data.get("end") or {}).get("dateTime"),
                html_link=data.get("htmlLink"),
            ),
        )
