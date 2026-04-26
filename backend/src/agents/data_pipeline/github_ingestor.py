"""data_pipeline/github_ingestor — INSERTs a row into dag_trigger_queue."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dag_trigger import DagTriggerQueue
from ...models.user import User
from ..base import Agent
from ..registry import register


class GitHubIngestorInput(BaseModel):
    repos: list[str] = Field(
        min_length=1,
        description="One or more 'owner/name' repos to ingest issues + PRs from.",
    )
    full_refresh: bool = Field(default=False)


class GitHubIngestorSummary(BaseModel):
    run_id: str
    status: str
    dag_id: str
    repos: list[str]


class GitHubIngestorOutput(BaseModel):
    data: dict[str, Any]
    summary: GitHubIngestorSummary


@register
class GitHubIngestorAgent(Agent):
    domain = "data_pipeline"
    name = "github_ingestor"
    description = (
        "Triggers async ingestion of issues + PRs across the supplied repos "
        "into ingested_github_activity. Returns a run_id."
    )
    input_schema = GitHubIngestorInput
    output_schema = GitHubIngestorOutput
    tool_dependencies = ["github_list_issues", "github_list_prs"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> GitHubIngestorOutput:
        assert isinstance(payload, GitHubIngestorInput)
        row = DagTriggerQueue(
            dag_id="github_ingestor",
            user_id=user.id,
            payload=payload.model_dump(),
            status="pending",
        )
        db.add(row)
        await db.commit()
        return GitHubIngestorOutput(
            data={
                "run_id": str(row.id),
                "status": row.status,
                "dag_id": row.dag_id,
                "repos": payload.repos,
            },
            summary=GitHubIngestorSummary(
                run_id=str(row.id),
                status=row.status,
                dag_id=row.dag_id,
                repos=payload.repos,
            ),
        )
