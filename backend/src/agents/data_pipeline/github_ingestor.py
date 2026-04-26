"""data_pipeline/github_ingestor — placeholder; Phase F."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class GitHubIngestorInput(BaseModel):
    repos: list[str] = Field(default_factory=list)
    full_refresh: bool = Field(default=False)


class GitHubIngestorOutput(BaseModel):
    data: dict[str, Any]
    summary: dict[str, Any]


@register
class GitHubIngestorAgent(Agent):
    domain = "data_pipeline"
    name = "github_ingestor"
    description = (
        "Triggers the Airflow DAG that pulls GitHub activity into Postgres. "
        "Phase E: not implemented — Phase F."
    )
    input_schema = GitHubIngestorInput
    output_schema = GitHubIngestorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> GitHubIngestorOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase F")
