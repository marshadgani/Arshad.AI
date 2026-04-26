"""github/repo_monitor — aggregate open issue + PR counts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.github.list_issues import (
    GitHubListIssues,
    ListIssuesInput,
)
from ...tools.github.list_prs import (
    GitHubListPrs,
    ListPrsInput,
)
from ..base import Agent
from ..registry import register


class RepoMonitorInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")


class RepoSnapshot(BaseModel):
    repo: str
    open_issues: int
    open_prs: int
    open_drafts: int


class RepoMonitorOutput(BaseModel):
    data: dict[str, Any]
    summary: RepoSnapshot


@register
class RepoMonitorAgent(Agent):
    domain = "github"
    name = "repo_monitor"
    description = (
        "Snapshot of open issues and PRs for a repo. Aggregates "
        "github_list_issues + github_list_prs into one call so the "
        "frontend dashboard widget can refresh both counts in one shot."
    )
    input_schema = RepoMonitorInput
    output_schema = RepoMonitorOutput
    tool_dependencies = ["github_list_issues", "github_list_prs"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> RepoMonitorOutput:
        assert isinstance(payload, RepoMonitorInput)
        issues = await GitHubListIssues()(
            user=user,
            db=db,
            payload=ListIssuesInput(repo=payload.repo, state="open", max_results=100),
        )
        prs = await GitHubListPrs()(
            user=user,
            db=db,
            payload=ListPrsInput(repo=payload.repo, state="open", max_results=100),
        )
        drafts = sum(1 for pr in prs.summary if pr.draft)
        return RepoMonitorOutput(
            data={"issues": issues.data, "prs": prs.data},
            summary=RepoSnapshot(
                repo=payload.repo,
                open_issues=len(issues.summary),
                open_prs=len(prs.summary),
                open_drafts=drafts,
            ),
        )
