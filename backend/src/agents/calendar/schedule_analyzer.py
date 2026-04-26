"""calendar/schedule_analyzer — events + overlap detection.

Phase E: deterministic. Counts overlapping events as conflicts. Phase B
will add a natural-language summary ('your morning is packed; nothing
after lunch').
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.calendar.list_events import (
    CalendarListEvents,
    EventSummary,
    ListEventsInput,
)
from ..base import Agent
from ..registry import register


class ScheduleAnalyzerInput(BaseModel):
    time_min: str = Field(description="RFC3339 start of analysis window")
    time_max: str = Field(description="RFC3339 end of analysis window")
    max_results: int = Field(default=100, ge=1, le=500)


class ConflictPair(BaseModel):
    a: str  # event id
    b: str  # event id


class ScheduleSummary(BaseModel):
    event_count: int
    conflict_count: int
    conflicts: list[ConflictPair]
    events: list[EventSummary]


class ScheduleAnalyzerOutput(BaseModel):
    data: dict[str, Any]
    summary: ScheduleSummary


def _parse(rfc3339: str | None) -> datetime | None:
    if not rfc3339:
        return None
    try:
        return datetime.fromisoformat(rfc3339.replace("Z", "+00:00"))
    except ValueError:
        return None


def _detect_conflicts(events: list[EventSummary]) -> list[ConflictPair]:
    parsed: list[tuple[EventSummary, datetime, datetime]] = []
    for e in events:
        s, t = _parse(e.start), _parse(e.end)
        if s and t and t > s:
            parsed.append((e, s, t))
    parsed.sort(key=lambda row: row[1])

    conflicts: list[ConflictPair] = []
    for i, (a, a_start, a_end) in enumerate(parsed):
        for b, b_start, b_end in parsed[i + 1 :]:
            if b_start >= a_end:
                break  # sorted — no further overlaps with a
            if b_start < a_end and a_start < b_end:
                conflicts.append(ConflictPair(a=a.id, b=b.id))
    return conflicts


@register
class ScheduleAnalyzerAgent(Agent):
    domain = "calendar"
    name = "schedule_analyzer"
    description = (
        "Lists events in a window and flags overlapping pairs as conflicts. "
        "Phase E: deterministic interval-overlap detection. Phase B will "
        "add narrative summaries."
    )
    input_schema = ScheduleAnalyzerInput
    output_schema = ScheduleAnalyzerOutput
    tool_dependencies = ["calendar_list_events"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ScheduleAnalyzerOutput:
        assert isinstance(payload, ScheduleAnalyzerInput)
        result = await CalendarListEvents()(
            user=user,
            db=db,
            payload=ListEventsInput(
                time_min=payload.time_min,
                time_max=payload.time_max,
                max_results=payload.max_results,
            ),
        )
        conflicts = _detect_conflicts(result.summary)
        return ScheduleAnalyzerOutput(
            data=result.data,
            summary=ScheduleSummary(
                event_count=len(result.summary),
                conflict_count=len(conflicts),
                conflicts=conflicts,
                events=result.summary,
            ),
        )
