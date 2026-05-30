"""github_get_commit — fetch a commit with its message + file changes.

Backs Phase B's code_summarizer agent. Returns the commit JSON +
truncated patch text per file (capped to 4k chars/file, 16k total) so
Claude can summarize without exhausting context.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import github
from ..registry import register


class GetCommitInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    sha: str = Field(
        min_length=7, max_length=40, description="Commit SHA (full or short)"
    )


class CommitFileSummary(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int
    patch_excerpt: str | None = None


class CommitSummary(BaseModel):
    sha: str
    url: str
    author: str | None
    message: str
    files_changed: int
    additions: int
    deletions: int
    files: list[CommitFileSummary]


class GetCommitOutput(BaseModel):
    data: dict[str, Any]
    summary: CommitSummary


_PER_FILE_PATCH_CAP = 4000
_TOTAL_PATCH_CAP = 16000


@register
class GitHubGetCommit(Tool):
    name = "github_get_commit"
    description = (
        "Fetch a single GitHub commit with its message, stats, and per-file "
        "patch excerpts (capped at 4k chars/file, 16k total). Used by "
        "code_summarizer to produce a one-sentence commit summary."
    )
    input_schema = GetCommitInput
    output_schema = GetCommitOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> GetCommitOutput:
        assert isinstance(payload, GetCommitInput)
        commit = await github.request(
            db=db,
            user=user,
            method="GET",
            path=f"/repos/{payload.repo}/commits/{payload.sha}",
        )
        if not isinstance(commit, dict):
            commit = {}

        files_in: list[dict[str, Any]] = commit.get("files") or []
        stats: dict[str, Any] = commit.get("stats") or {}
        author_block = (
            commit.get("author") or commit.get("commit", {}).get("author") or {}
        )

        files: list[CommitFileSummary] = []
        running_total = 0
        for f in files_in:
            patch = f.get("patch")
            if patch:
                snippet = patch[:_PER_FILE_PATCH_CAP]
                if running_total + len(snippet) > _TOTAL_PATCH_CAP:
                    snippet = snippet[: max(0, _TOTAL_PATCH_CAP - running_total)]
                running_total += len(snippet)
            else:
                snippet = None
            files.append(
                CommitFileSummary(
                    filename=f.get("filename", ""),
                    status=f.get("status", ""),
                    additions=int(f.get("additions") or 0),
                    deletions=int(f.get("deletions") or 0),
                    patch_excerpt=snippet,
                )
            )

        return GetCommitOutput(
            data=commit,
            summary=CommitSummary(
                sha=commit.get("sha", payload.sha),
                url=commit.get("html_url", ""),
                author=(
                    author_block.get("login")
                    if isinstance(author_block, dict)
                    else None
                )
                or (commit.get("commit", {}).get("author") or {}).get("name"),
                message=(commit.get("commit") or {}).get("message", ""),
                files_changed=len(files),
                additions=int(stats.get("additions") or 0),
                deletions=int(stats.get("deletions") or 0),
                files=files,
            ),
        )
