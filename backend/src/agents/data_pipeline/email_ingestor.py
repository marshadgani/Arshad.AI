"""data_pipeline/email_ingestor — placeholder; Phase F."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class EmailIngestorInput(BaseModel):
    full_refresh: bool = Field(default=False)


class EmailIngestorOutput(BaseModel):
    data: dict[str, Any]
    summary: dict[str, Any]


@register
class EmailIngestorAgent(Agent):
    domain = "data_pipeline"
    name = "email_ingestor"
    description = (
        "Triggers the Airflow DAG that pulls Gmail threads into Postgres. "
        "Phase E: not implemented — Phase F."
    )
    input_schema = EmailIngestorInput
    output_schema = EmailIngestorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EmailIngestorOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase F")
