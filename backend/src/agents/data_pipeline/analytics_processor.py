"""data_pipeline/analytics_processor — INSERTs a row into dag_trigger_queue."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dag_trigger import DagTriggerQueue
from ...models.user import User
from ..base import Agent
from ..registry import register


class AnalyticsProcessorInput(BaseModel):
    window_days: int = Field(default=7, ge=1, le=365)


class AnalyticsProcessorSummary(BaseModel):
    run_id: str
    status: str
    dag_id: str
    window_days: int


class AnalyticsProcessorOutput(BaseModel):
    data: dict[str, Any]
    summary: AnalyticsProcessorSummary


@register
class AnalyticsProcessorAgent(Agent):
    domain = "data_pipeline"
    name = "analytics_processor"
    description = (
        "Triggers async aggregation of ingested_* tables into "
        "ingested_analytics_summary for the given window. Returns a run_id."
    )
    input_schema = AnalyticsProcessorInput
    output_schema = AnalyticsProcessorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> AnalyticsProcessorOutput:
        assert isinstance(payload, AnalyticsProcessorInput)
        row = DagTriggerQueue(
            dag_id="analytics_processor",
            user_id=user.id,
            payload=payload.model_dump(),
            status="pending",
        )
        db.add(row)
        await db.commit()
        return AnalyticsProcessorOutput(
            data={
                "run_id": str(row.id),
                "status": row.status,
                "dag_id": row.dag_id,
                "window_days": payload.window_days,
            },
            summary=AnalyticsProcessorSummary(
                run_id=str(row.id),
                status=row.status,
                dag_id=row.dag_id,
                window_days=payload.window_days,
            ),
        )
