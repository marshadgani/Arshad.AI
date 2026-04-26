"""github/code_summarizer — placeholder; needs commit-fetch tool not in Phase D.

Phase E: raises AgentNotImplemented. Phase B will add a github_get_commit
tool and wire Claude to summarise diffs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class CodeSummarizerInput(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    sha: str = Field(min_length=7, description="Commit SHA (full or short)")


class CodeSummary(BaseModel):
    repo: str
    sha: str
    summary_text: str | None
    files_changed: int
    is_heuristic: bool = True


class CodeSummarizerOutput(BaseModel):
    data: dict[str, Any]
    summary: CodeSummary


@register
class CodeSummarizerAgent(Agent):
    domain = "github"
    name = "code_summarizer"
    description = (
        "Plain-English summary of a GitHub commit. Phase E: not implemented "
        "(needs github_get_commit tool which is not in Phase D's 12). "
        "Phase B will add the tool and Claude integration."
    )
    input_schema = CodeSummarizerInput
    output_schema = CodeSummarizerOutput
    tool_dependencies: list[str] = []  # to be added with github_get_commit in Phase B

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CodeSummarizerOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase B")
