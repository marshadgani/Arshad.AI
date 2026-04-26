"""github_get_pr — fetch a single PR with its diff URL.

GitHub returns the diff via a separate URL; we fetch the structured
PR JSON via /pulls/{number} and the unified diff via /pulls/{number}.diff
in a second request. Phase B's pr_reviewer agent consumes both.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import github
from ..registry import register


class GetPrInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    number: int = Field(gt=0)


class PrSummary(BaseModel):
    number: int
    title: str
    state: str
    url: str
    author: str | None
    head: str
    base: str
    draft: bool
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None
    diff_excerpt: str | None = None


class GetPrOutput(BaseModel):
    data: dict[str, Any]
    summary: PrSummary


_DIFF_EXCERPT_LEN = 12000  # cap diff body so the agent doesn't blow the context window


@register
class GitHubGetPr(Tool):
    name = "github_get_pr"
    description = (
        "Fetch a single GitHub PR with its diff. Returns structured PR JSON + "
        "a truncated unified diff under summary.diff_excerpt (up to 12k chars) "
        "so callers can review changes without a second tool call."
    )
    input_schema = GetPrInput
    output_schema = GetPrOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> GetPrOutput:
        assert isinstance(payload, GetPrInput)
        pr = await github.request(
            db=db,
            user=user,
            method="GET",
            path=f"/repos/{payload.repo}/pulls/{payload.number}",
        )
        if not isinstance(pr, dict):
            pr = {}

        diff_text: str | None = None
        try:
            # Diff is returned by GitHub when Accept: application/vnd.github.v3.diff,
            # but our client hard-codes vnd.github+json. Hit the .diff URL directly
            # via httpx without auth-header reuse complications.
            import httpx

            from ..token_service import get_access_token

            token, _ = await get_access_token(db, user, "github")
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://api.github.com/repos/{payload.repo}/pulls/{payload.number}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github.v3.diff",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            if resp.status_code == 200:
                diff_text = resp.text[:_DIFF_EXCERPT_LEN]
        except Exception:
            diff_text = None

        return GetPrOutput(
            data={"pr": pr, "diff": diff_text},
            summary=PrSummary(
                number=pr["number"],
                title=pr["title"],
                state=pr["state"],
                url=pr["html_url"],
                author=(pr.get("user") or {}).get("login"),
                head=pr["head"]["ref"],
                base=pr["base"]["ref"],
                draft=pr.get("draft", False),
                additions=pr.get("additions"),
                deletions=pr.get("deletions"),
                changed_files=pr.get("changed_files"),
                diff_excerpt=diff_text,
            ),
        )
