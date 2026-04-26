"""data_pipeline/calendar_ingestor — INSERTs a row into dag_trigger_queue.

The queue worker (or Airflow sensor) picks up the row and calls
``services/ingestion/runner.run`` to do the actual ingestion. This agent
returns immediately with the run_id; status is polled via
``GET /api/v1/agents/data_pipeline/runs/{run_id}``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dag_trigger import DagTriggerQueue
from ...models.user import User
from ..base import Agent
from ..registry import register


class CalendarIngestorInput(BaseModel):
    full_refresh: bool = Field(default=False)


class CalendarIngestorSummary(BaseModel):
    run_id: str
    status: str
    dag_id: str


class CalendarIngestorOutput(BaseModel):
    data: dict[str, Any]
    summary: CalendarIngestorSummary


@register
class CalendarIngestorAgent(Agent):
    domain = "data_pipeline"
    name = "calendar_ingestor"
    description = (
        "Triggers async ingestion of the user's Google Calendar events into "
        "ingested_calendar_events. Returns a run_id; poll runs/{run_id} "
        "for status. Phase F: real implementation."
    )
    input_schema = CalendarIngestorInput
    output_schema = CalendarIngestorOutput
    tool_dependencies = ["calendar_list_events"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CalendarIngestorOutput:
        assert isinstance(payload, CalendarIngestorInput)
        row = DagTriggerQueue(
            dag_id="calendar_ingestor",
            user_id=user.id,
            payload=payload.model_dump(),
            status="pending",
        )
        db.add(row)
        await db.commit()
        return CalendarIngestorOutput(
            data={"run_id": str(row.id), "status": row.status, "dag_id": row.dag_id},
            summary=CalendarIngestorSummary(
                run_id=str(row.id), status=row.status, dag_id=row.dag_id
            ),
        )
