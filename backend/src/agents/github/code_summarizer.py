"""github/code_summarizer — Claude-summarized commit (Phase B real impl).

Phase E was a placeholder (no github_get_commit existed). Phase B has
the tool; agent now fetches the commit + per-file patch excerpts and
asks Haiku for a one-sentence summary.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...services import ai
from ...tools.github.get_commit import GetCommitInput, GitHubGetCommit
from ..base import Agent
from ..registry import register

_SYSTEM_PROMPT = """\
Summarize this Git commit in ONE sentence (max 25 words). Focus on what
changed, not why. Output plain text only — no commit hash, no markdown.
"""


class CodeSummarizerInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    sha: str = Field(min_length=7, max_length=40)


class CodeSummary(BaseModel):
    repo: str
    sha: str
    url: str
    summary_text: str | None
    files_changed: int
    additions: int
    deletions: int
    is_heuristic: bool = False


class CodeSummarizerOutput(BaseModel):
    data: dict[str, Any]
    summary: CodeSummary


@register
class CodeSummarizerAgent(Agent):
    domain = "github"
    name = "code_summarizer"
    description = (
        "One-sentence summary of a GitHub commit via Claude. Fetches the "
        "commit + per-file patch excerpts; outputs plain-text summary."
    )
    input_schema = CodeSummarizerInput
    output_schema = CodeSummarizerOutput
    tool_dependencies = ["github_get_commit"]
    # Plain-English diff-to-summary needs reasoning; Sonnet, not Haiku.
    model = "claude-sonnet-4-6"

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CodeSummarizerOutput:
        assert isinstance(payload, CodeSummarizerInput)
        commit = await GitHubGetCommit()(
            user=user,
            db=db,
            payload=GetCommitInput(repo=payload.repo, sha=payload.sha),
        )
        s = commit.summary

        prompt_lines = [
            f"Repo: {payload.repo}",
            f"SHA: {s.sha}",
            f"Commit message: {s.message}",
            f"Stats: +{s.additions} / -{s.deletions} across {s.files_changed} files",
            "",
            "Files:",
        ]
        for f in s.files:
            prompt_lines.append(
                f"  - {f.filename} ({f.status}, +{f.additions}/-{f.deletions})"
            )
            if f.patch_excerpt:
                prompt_lines.append(
                    "    PATCH:\n    " + f.patch_excerpt.replace("\n", "\n    ")
                )

        prompt_body = "\n".join(prompt_lines)

        msg = await ai.call(
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt_body}],
            max_tokens=80,
            model=self.model,
        )
        summary_text = "".join(
            block.get("text", "")
            for block in msg.get("content", [])
            if block.get("type") == "text"
        ).strip()

        return CodeSummarizerOutput(
            data=commit.data,
            summary=CodeSummary(
                repo=payload.repo,
                sha=s.sha,
                url=s.url,
                summary_text=summary_text or None,
                files_changed=s.files_changed,
                additions=s.additions,
                deletions=s.deletions,
                is_heuristic=False,
            ),
        )
