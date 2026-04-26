"""data_pipeline/calendar_ingestor — placeholder; Phase F triggers Airflow."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class CalendarIngestorInput(BaseModel):
    full_refresh: bool = Field(default=False)


class CalendarIngestorOutput(BaseModel):
    data: dict[str, Any]
    summary: dict[str, Any]


@register
class CalendarIngestorAgent(Agent):
    domain = "data_pipeline"
    name = "calendar_ingestor"
    description = (
        "Triggers the Airflow DAG that pulls Calendar events into Postgres. "
        "Phase E: not implemented — Phase F lands the DAG and the trigger API."
    )
    input_schema = CalendarIngestorInput
    output_schema = CalendarIngestorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CalendarIngestorOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase F")
