"""data_pipeline/email_ingestor — INSERTs a row into dag_trigger_queue."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dag_trigger import DagTriggerQueue
from ...models.user import User
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
        row = DagTriggerQueue(
            dag_id="email_ingestor",
            user_id=user.id,
            payload=payload.model_dump(),
            status="pending",
        )
        db.add(row)
        await db.commit()
        return EmailIngestorOutput(
            data={"run_id": str(row.id), "status": row.status, "dag_id": row.dag_id},
            summary=EmailIngestorSummary(
                run_id=str(row.id), status=row.status, dag_id=row.dag_id
            ),
        )
