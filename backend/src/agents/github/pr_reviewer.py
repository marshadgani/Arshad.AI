"""github/pr_reviewer — open-PR list + heuristic counts.

Phase E: lists open PRs and surfaces draft / mergeable counts. Phase B
will fetch each PR's diff and produce a code review summary via Claude.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.github.list_prs import (
    GitHubListPrs,
    ListPrsInput,
    PrSummary,
)
from ..base import Agent
from ..registry import register


class PrReviewerInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    max_results: int = Field(default=30, ge=1, le=100)


class PrReviewerSummary(BaseModel):
    open_count: int
    draft_count: int
    ready_for_review: int
    prs: list[PrSummary]
    is_heuristic: bool = Field(
        default=True,
        description="Phase E flag: counts only — no diff review yet. Phase B replaces with Claude.",
    )


class PrReviewerOutput(BaseModel):
    data: list[dict[str, Any]]
    summary: PrReviewerSummary


@register
class PrReviewerAgent(Agent):
    domain = "github"
    name = "pr_reviewer"
    description = (
        "Lists open PRs in a repo with draft/ready counts. Phase E: counts "
        "only. Phase B will fetch diffs and produce review summaries."
    )
    input_schema = PrReviewerInput
    output_schema = PrReviewerOutput
    tool_dependencies = ["github_list_prs"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> PrReviewerOutput:
        assert isinstance(payload, PrReviewerInput)
        result = await GitHubListPrs()(
            user=user,
            db=db,
            payload=ListPrsInput(
                repo=payload.repo, state="open", max_results=payload.max_results
            ),
        )
        drafts = sum(1 for pr in result.summary if pr.draft)
        return PrReviewerOutput(
            data=result.data,
            summary=PrReviewerSummary(
                open_count=len(result.summary),
                draft_count=drafts,
                ready_for_review=len(result.summary) - drafts,
                prs=result.summary,
            ),
        )
