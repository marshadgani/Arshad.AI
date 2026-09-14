"""data_pipeline/analytics_processor — INSERTs a row into dag_trigger_queue."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...services.ingestion.enqueue import enqueue_dag_job
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
        # enqueue_dag_job, not a bare INSERT: uq_dag_trigger_queue_user_
        # dag_inflight (FEAT-144) makes a second row for the same
        # (user_id, dag_id) while one is pending/picked raise
        # IntegrityError. Reusing the in-flight run is the right answer
        # here anyway — two identical ingestions would double-call the
        # provider API.
        job = await enqueue_dag_job(
            db,
            dag_id="analytics_processor",
            user_id=user.id,
            payload=payload.model_dump(),
        )
        return AnalyticsProcessorOutput(
            data={
                "run_id": job.job_id,
                "status": job.status,
                "dag_id": "analytics_processor",
                "window_days": payload.window_days,
            },
            summary=AnalyticsProcessorSummary(
                run_id=job.job_id,
                status=job.status,
                dag_id="analytics_processor",
                window_days=payload.window_days,
            ),
        )
