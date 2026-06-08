"""calendar_update_event — patch an existing event."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import google_calendar
from ..registry import register


class UpdateEventPatch(BaseModel):
    title: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
    location: str | None = None


class UpdateEventInput(BaseModel):
    event_id: str = Field(min_length=1)
    patch: UpdateEventPatch
    calendar_id: str = Field(default="primary")
    send_updates: str = Field(default="none")


class UpdateEventSummary(BaseModel):
    id: str
    title: str | None
    start: str | None
    end: str | None
    html_link: str | None


class UpdateEventOutput(BaseModel):
    data: dict[str, Any]
    summary: UpdateEventSummary


@register
class CalendarUpdateEvent(Tool):
    name = "calendar_update_event"
    description = (
        "Patch an existing Google Calendar event. Only fields present in 'patch' "
        "are updated; the rest are preserved. Uses HTTP PATCH."
    )
    input_schema = UpdateEventInput
    output_schema = UpdateEventOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> UpdateEventOutput:
        assert isinstance(payload, UpdateEventInput)
        body: dict[str, Any] = {}
        if payload.patch.title is not None:
            body["summary"] = payload.patch.title
        if payload.patch.start is not None:
            body["start"] = {"dateTime": payload.patch.start}
        if payload.patch.end is not None:
            body["end"] = {"dateTime": payload.patch.end}
        if payload.patch.description is not None:
            body["description"] = payload.patch.description
        if payload.patch.location is not None:
            body["location"] = payload.patch.location

        data = await google_calendar.request(
            db=db,
            user=user,
            method="PATCH",
            path=f"/calendars/{payload.calendar_id}/events/{payload.event_id}",
            params={"sendUpdates": payload.send_updates},
            json=body,
        )
        return UpdateEventOutput(
            data=data or {},
            summary=UpdateEventSummary(
                id=data["id"],
                title=data.get("summary"),
                start=(data.get("start") or {}).get("dateTime"),
                end=(data.get("end") or {}).get("dateTime"),
                html_link=data.get("htmlLink"),
            ),
        )
