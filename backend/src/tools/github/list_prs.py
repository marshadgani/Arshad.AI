"""github_list_prs — list pull requests in a repo."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import github
from ..registry import register


class ListPrsInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    state: Literal["open", "closed", "all"] = "open"
    base: str | None = Field(default=None, description="Filter by base branch")
    head: str | None = Field(default=None, description="Filter by head branch")
    max_results: int = Field(default=30, ge=1, le=100)


class PrSummary(BaseModel):
    number: int
    title: str
    state: str
    url: str
    author: str | None
    head: str
    base: str
    draft: bool
    updated_at: str


class ListPrsOutput(BaseModel):
    data: list[dict[str, Any]]
    summary: list[PrSummary]


@register
class GitHubListPrs(Tool):
    name = "github_list_prs"
    description = (
        "List pull requests in a GitHub repo. Filter by state, base branch, "
        "head branch (owner:branch). Returns up to max_results PRs ordered by "
        "most recently updated."
    )
    input_schema = ListPrsInput
    output_schema = ListPrsOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ListPrsOutput:
        assert isinstance(payload, ListPrsInput)
        params: dict[str, Any] = {
            "state": payload.state,
            "per_page": payload.max_results,
            "sort": "updated",
            "direction": "desc",
        }
        if payload.base:
            params["base"] = payload.base
        if payload.head:
            params["head"] = payload.head

        data = await github.request(
            db=db,
            user=user,
            method="GET",
            path=f"/repos/{payload.repo}/pulls",
            params=params,
        )
        items: list[dict[str, Any]] = data if isinstance(data, list) else []

        return ListPrsOutput(
            data=items,
            summary=[
                PrSummary(
                    number=pr["number"],
                    title=pr["title"],
                    state=pr["state"],
                    url=pr["html_url"],
                    author=(pr.get("user") or {}).get("login"),
                    head=pr["head"]["ref"],
                    base=pr["base"]["ref"],
                    draft=pr.get("draft", False),
                    updated_at=pr["updated_at"],
                )
                for pr in items
            ],
        )
