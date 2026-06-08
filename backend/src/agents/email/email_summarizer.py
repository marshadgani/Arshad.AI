"""email/email_summarizer — Claude-summarized Gmail thread (Phase B real impl).

Phase E heuristic returned the first 200 chars of the latest message.
Phase B fetches the thread, formats sender/subject/body for each
message, and calls Haiku with a tight 2-sentence-summary prompt.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...services import ai
from ...tools.gmail.get_thread import GetThreadInput, GmailGetThread
from ..base import Agent
from ..registry import register

_SYSTEM_PROMPT = """\
Summarize this Gmail thread in 1-2 short sentences focused on action items
or open questions for the recipient. Output plain text only — no JSON, no
markdown. If there's nothing actionable, say so in one sentence.
"""


class EmailSummarizerInput(BaseModel):
    thread_id: str = Field(min_length=1)


class EmailSummary(BaseModel):
    thread_id: str
    latest_subject: str | None
    latest_from: str | None
    summary_text: str | None
    message_count: int
    is_heuristic: bool = False


class EmailSummarizerOutput(BaseModel):
    data: dict[str, Any]
    summary: EmailSummary


_TRANSCRIPT_CHAR_CAP = 16000


@register
class EmailSummarizerAgent(Agent):
    domain = "email"
    name = "email_summarizer"
    description = (
        "Summarizes a Gmail thread with a Sonnet call focused on action items. "
        "Phase B: real Claude summarisation. is_heuristic flag now false."
    )
    input_schema = EmailSummarizerInput
    output_schema = EmailSummarizerOutput
    tool_dependencies = ["gmail_get_thread"]
    # Summarisation quality scales with reasoning — Sonnet, not Haiku.
    model = "claude-sonnet-4-6"

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EmailSummarizerOutput:
        assert isinstance(payload, EmailSummarizerInput)
        thread = await GmailGetThread()(
            user=user, db=db, payload=GetThreadInput(thread_id=payload.thread_id)
        )
        messages = thread.summary.messages
        latest = messages[-1] if messages else None

        transcript_parts: list[str] = []
        for m in messages:
            transcript_parts.append(
                f"From: {m.from_addr or '(unknown)'}\n"
                f"Date: {m.date or '(unknown)'}\n"
                f"Subject: {m.subject or '(no subject)'}\n"
                f"---\n"
                f"{(m.body_plain or '(no plain body)')[:2000]}"
            )
        transcript = "\n\n=====\n\n".join(transcript_parts)[:_TRANSCRIPT_CHAR_CAP]

        summary_text: str | None = None
        if transcript.strip():
            msg = await ai.call(
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": transcript}],
                max_tokens=200,
                model=self.model,
            )
            summary_text = "".join(
                block.get("text", "")
                for block in msg.get("content", [])
                if block.get("type") == "text"
            ).strip()

        return EmailSummarizerOutput(
            data=thread.data,
            summary=EmailSummary(
                thread_id=payload.thread_id,
                latest_subject=latest.subject if latest else None,
                latest_from=latest.from_addr if latest else None,
                summary_text=summary_text,
                message_count=len(messages),
                is_heuristic=False,
            ),
        )
