"""github/pr_reviewer — real PR review via Claude (Phase B impl).

Phase E heuristic returned counts only. Phase B fetches the PR + diff
via github_get_pr and feeds them to Haiku with a 'one-paragraph review
focused on concerns' prompt.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...services import ai
from ...tools.github.get_pr import GetPrInput, GitHubGetPr
from ..base import Agent
from ..registry import register

_SYSTEM_PROMPT = """\
Review this GitHub pull request. Focus on concerns: bugs, missing
edge cases, breaking changes, security issues. Output one short
paragraph (3-5 sentences). Output plain text only.

If there are no concerns, say "Looks good — no concerns flagged." in
one sentence.
"""


class PrReviewerInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    number: int = Field(gt=0)


class PrReviewSummary(BaseModel):
    repo: str
    number: int
    title: str
    state: str
    url: str
    additions: int | None
    deletions: int | None
    changed_files: int | None
    review_text: str | None
    is_heuristic: bool = False


class PrReviewerOutput(BaseModel):
    data: dict[str, Any]
    summary: PrReviewSummary


@register
class PrReviewerAgent(Agent):
    domain = "github"
    name = "pr_reviewer"
    description = (
        "Reviews a GitHub PR via Claude. Fetches the PR + diff and produces "
        "a one-paragraph review focused on concerns. Phase B real impl."
    )
    input_schema = PrReviewerInput
    output_schema = PrReviewerOutput
    tool_dependencies = ["github_get_pr"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> PrReviewerOutput:
        assert isinstance(payload, PrReviewerInput)
        pr_result = await GitHubGetPr()(
            user=user,
            db=db,
            payload=GetPrInput(repo=payload.repo, number=payload.number),
        )

        s = pr_result.summary
        prompt_body = (
            f"Repo: {payload.repo}\n"
            f"PR #{s.number}: {s.title}\n"
            f"State: {s.state} (draft={s.draft})\n"
            f"Author: {s.author or '(unknown)'}\n"
            f"Branches: {s.head} -> {s.base}\n"
            f"Stats: +{s.additions or 0} / -{s.deletions or 0} across "
            f"{s.changed_files or 0} files\n\n"
            f"DIFF:\n{s.diff_excerpt or '(diff unavailable)'}"
        )

        review_text: str | None = None
        if s.diff_excerpt:
            msg = await ai.call(
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt_body}],
                max_tokens=400,
            )
            review_text = "".join(
                block.get("text", "")
                for block in msg.get("content", [])
                if block.get("type") == "text"
            ).strip()

        return PrReviewerOutput(
            data=pr_result.data,
            summary=PrReviewSummary(
                repo=payload.repo,
                number=s.number,
                title=s.title,
                state=s.state,
                url=s.url,
                additions=s.additions,
                deletions=s.deletions,
                changed_files=s.changed_files,
                review_text=review_text,
                is_heuristic=False,
            ),
        )
