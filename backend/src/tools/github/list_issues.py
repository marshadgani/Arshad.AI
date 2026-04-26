"""github_list_issues — list issues in a repo (excludes PRs)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import github
from ..registry import register


class ListIssuesInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$", description="owner/name")
    state: Literal["open", "closed", "all"] = "open"
    labels: list[str] = Field(default_factory=list)
    assignee: str | None = None
    max_results: int = Field(default=30, ge=1, le=100)


class IssueSummary(BaseModel):
    number: int
    title: str
    state: str
    url: str
    author: str | None
    labels: list[str]
    updated_at: str
    comments: int


class ListIssuesOutput(BaseModel):
    data: list[dict[str, Any]]
    summary: list[IssueSummary]


@register
class GitHubListIssues(Tool):
    name = "github_list_issues"
    description = (
        "List issues in a GitHub repo. Filters by state (open/closed/all), "
        "labels (AND), and assignee. GitHub's issues API also returns PRs — "
        "this tool filters them out so 'issues' means actual issues."
    )
    input_schema = ListIssuesInput
    output_schema = ListIssuesOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ListIssuesOutput:
        assert isinstance(payload, ListIssuesInput)
        params: dict[str, Any] = {
            "state": payload.state,
            "per_page": payload.max_results,
        }
        if payload.labels:
            params["labels"] = ",".join(payload.labels)
        if payload.assignee:
            params["assignee"] = payload.assignee

        data = await github.request(
            db=db,
            user=user,
            method="GET",
            path=f"/repos/{payload.repo}/issues",
            params=params,
        )
        items: list[dict[str, Any]] = data if isinstance(data, list) else []
        # GitHub returns PRs in /issues; filter them out so callers don't get surprised.
        issues_only = [i for i in items if "pull_request" not in i]

        return ListIssuesOutput(
            data=issues_only,
            summary=[
                IssueSummary(
                    number=i["number"],
                    title=i["title"],
                    state=i["state"],
                    url=i["html_url"],
                    author=(i.get("user") or {}).get("login"),
                    labels=[lbl.get("name", "") for lbl in i.get("labels") or []],
                    updated_at=i["updated_at"],
                    comments=i.get("comments", 0),
                )
                for i in issues_only
            ],
        )
