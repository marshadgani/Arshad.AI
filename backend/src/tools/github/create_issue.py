"""github_create_issue — open a new issue in a repo."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import github
from ..registry import register


class CreateIssueInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    title: str = Field(min_length=1, max_length=256)
    body: str | None = None
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)


class CreateIssueSummary(BaseModel):
    number: int
    url: str
    title: str
    state: str


class CreateIssueOutput(BaseModel):
    data: dict[str, Any]
    summary: CreateIssueSummary


@register
class GitHubCreateIssue(Tool):
    name = "github_create_issue"
    description = (
        "Open a new issue in a GitHub repo. The authenticated user becomes "
        "the issue author. labels/assignees are optional; GitHub silently "
        "ignores labels that don't exist on the repo (no error)."
    )
    input_schema = CreateIssueInput
    output_schema = CreateIssueOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CreateIssueOutput:
        assert isinstance(payload, CreateIssueInput)
        body: dict[str, Any] = {"title": payload.title}
        if payload.body:
            body["body"] = payload.body
        if payload.labels:
            body["labels"] = payload.labels
        if payload.assignees:
            body["assignees"] = payload.assignees

        data = await github.request(
            db=db,
            user=user,
            method="POST",
            path=f"/repos/{payload.repo}/issues",
            json=body,
        )
        if not isinstance(data, dict):
            data = {}
        return CreateIssueOutput(
            data=data,
            summary=CreateIssueSummary(
                number=data["number"],
                url=data["html_url"],
                title=data["title"],
                state=data["state"],
            ),
        )
