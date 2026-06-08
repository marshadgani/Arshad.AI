"""github_update_issue — patch issue title/body/state/labels/assignees."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import github
from ..registry import register


class UpdateIssuePatch(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    body: str | None = None
    state: Literal["open", "closed"] | None = None
    state_reason: Literal["completed", "not_planned", "reopened"] | None = None
    labels: list[str] | None = Field(
        default=None,
        description="REPLACES the label list (not additive). Use [] to clear.",
    )
    assignees: list[str] | None = Field(
        default=None,
        description="REPLACES the assignee list (not additive). Use [] to clear.",
    )


class UpdateIssueInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    number: int = Field(gt=0)
    patch: UpdateIssuePatch


class UpdateIssueSummary(BaseModel):
    number: int
    url: str
    state: str
    title: str


class UpdateIssueOutput(BaseModel):
    data: dict[str, Any]
    summary: UpdateIssueSummary


@register
class GitHubUpdateIssue(Tool):
    name = "github_update_issue"
    description = (
        "Patch an existing GitHub issue. Only fields present in 'patch' change. "
        "Setting labels=[] CLEARS labels (replaces, not adds). Use state_reason "
        "alongside state='closed' to mark completed vs not_planned."
    )
    input_schema = UpdateIssueInput
    output_schema = UpdateIssueOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> UpdateIssueOutput:
        assert isinstance(payload, UpdateIssueInput)
        body: dict[str, Any] = {}
        p = payload.patch
        if p.title is not None:
            body["title"] = p.title
        if p.body is not None:
            body["body"] = p.body
        if p.state is not None:
            body["state"] = p.state
        if p.state_reason is not None:
            body["state_reason"] = p.state_reason
        if p.labels is not None:
            body["labels"] = p.labels
        if p.assignees is not None:
            body["assignees"] = p.assignees

        data = await github.request(
            db=db,
            user=user,
            method="PATCH",
            path=f"/repos/{payload.repo}/issues/{payload.number}",
            json=body,
        )
        if not isinstance(data, dict):
            data = {}
        return UpdateIssueOutput(
            data=data,
            summary=UpdateIssueSummary(
                number=data["number"],
                url=data["html_url"],
                state=data["state"],
                title=data["title"],
            ),
        )
