"""data_pipeline/email_ingestor — INSERTs a row into dag_trigger_queue."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...services.ingestion.enqueue import enqueue_dag_job
from ..base import Agent
from ..registry import register


class EmailIngestorInput(BaseModel):
    full_refresh: bool = Field(default=False)


class EmailIngestorSummary(BaseModel):
    run_id: str
    status: str
    dag_id: str


class EmailIngestorOutput(BaseModel):
    data: dict[str, Any]
    summary: EmailIngestorSummary


@register
class EmailIngestorAgent(Agent):
    domain = "data_pipeline"
    name = "email_ingestor"
    description = (
        "Triggers async ingestion of the user's Gmail thread metadata into "
        "ingested_gmail_threads. Returns a run_id; poll runs/{run_id} for status."
    )
    input_schema = EmailIngestorInput
    output_schema = EmailIngestorOutput
    tool_dependencies = ["gmail_search_threads"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EmailIngestorOutput:
        assert isinstance(payload, EmailIngestorInput)
        # enqueue_dag_job, not a bare INSERT: uq_dag_trigger_queue_user_
        # dag_inflight (FEAT-144) makes a second row for the same
        # (user_id, dag_id) while one is pending/picked raise
        # IntegrityError. Reusing the in-flight run is the right answer
        # here anyway — two identical ingestions would double-call the
        # provider API.
        job = await enqueue_dag_job(
            db, dag_id="email_ingestor", user_id=user.id, payload=payload.model_dump()
        )
        return EmailIngestorOutput(
            data={
                "run_id": job.job_id,
                "status": job.status,
                "dag_id": "email_ingestor",
            },
            summary=EmailIngestorSummary(
                run_id=job.job_id, status=job.status, dag_id="email_ingestor"
            ),
        )
