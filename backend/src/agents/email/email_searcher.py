"""email/email_searcher — Gmail search pass-through."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.gmail.search_threads import (
    GmailSearchThreads,
    SearchThreadsInput,
    ThreadSummary,
)
from ..base import Agent
from ..registry import register


class EmailSearcherOutput(BaseModel):
    data: dict[str, Any]
    summary: list[ThreadSummary]


@register
class EmailSearcherAgent(Agent):
    domain = "email"
    name = "email_searcher"
    description = (
        "Searches Gmail threads using Gmail's search syntax. Phase E: "
        "pass-through to gmail_search_threads. Phase B will translate "
        "natural-language queries ('emails from Sarah this week') into "
        "Gmail's syntax."
    )
    input_schema = SearchThreadsInput
    output_schema = EmailSearcherOutput
    tool_dependencies = ["gmail_search_threads"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EmailSearcherOutput:
        result = await GmailSearchThreads()(user=user, db=db, payload=payload)
        return EmailSearcherOutput(data=result.data, summary=result.summary)
