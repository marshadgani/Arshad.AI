"""email/email_summarizer — heuristic thread summary; Phase B replaces with Claude.

Phase E heuristic: returns first 200 chars of the latest message's plain
body + sender + subject. No actual summarisation. Phase B replaces with
a real Claude call that reads the thread and produces an action-oriented
summary.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.gmail.get_thread import (
    GetThreadInput,
    GmailGetThread,
)
from ..base import Agent
from ..registry import register


class EmailSummarizerInput(BaseModel):
    thread_id: str = Field(min_length=1)


class EmailSummary(BaseModel):
    thread_id: str
    latest_subject: str | None
    latest_from: str | None
    latest_excerpt: str | None
    message_count: int
    is_heuristic: bool = Field(
        default=True,
        description="Phase E flag: this summary is a 200-char prefix, not real summarisation. Phase B replaces with Claude.",
    )


class EmailSummarizerOutput(BaseModel):
    data: dict[str, Any]
    summary: EmailSummary


_EXCERPT_LEN = 200


@register
class EmailSummarizerAgent(Agent):
    domain = "email"
    name = "email_summarizer"
    description = (
        "Returns a thread excerpt (first 200 chars of the latest message). "
        "Phase E: heuristic only — Phase B replaces with Claude summarisation."
    )
    input_schema = EmailSummarizerInput
    output_schema = EmailSummarizerOutput
    tool_dependencies = ["gmail_get_thread"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EmailSummarizerOutput:
        assert isinstance(payload, EmailSummarizerInput)
        result = await GmailGetThread()(
            user=user, db=db, payload=GetThreadInput(thread_id=payload.thread_id)
        )
        messages = result.summary.messages
        latest = messages[-1] if messages else None
        excerpt = None
        if latest and latest.body_plain:
            excerpt = latest.body_plain.strip()[:_EXCERPT_LEN]
        return EmailSummarizerOutput(
            data=result.data,
            summary=EmailSummary(
                thread_id=payload.thread_id,
                latest_subject=latest.subject if latest else None,
                latest_from=latest.from_addr if latest else None,
                latest_excerpt=excerpt,
                message_count=len(messages),
            ),
        )
