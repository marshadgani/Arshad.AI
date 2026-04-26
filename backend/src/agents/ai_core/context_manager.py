"""ai_core/context_manager — read + summarize a session's history.

Phase B: real implementation. Reports message count, approximate token
count, and (optionally) a one-paragraph Claude-generated summary of
the conversation so far. Useful for callers that want to know "what
was this session about?" without scanning all messages.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.conversation import ConversationMessage, ConversationSession
from ...models.user import User
from ...services import ai
from ..base import Agent, AgentError
from ..registry import register

_SUMMARY_PROMPT = """\
Summarize this conversation in one short paragraph (max 3 sentences).
Focus on what the user asked for and what was done. Output plain text only.
"""


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ContextManagerInput(BaseModel):
    session_id: str = Field(min_length=1)
    summarize: bool = Field(
        default=False,
        description="If true, run a Claude call to generate a paragraph summary.",
    )


class ContextSummary(BaseModel):
    session_id: str
    title: str
    message_count: int
    approximate_tokens: int
    summary_text: str | None


class ContextManagerOutput(BaseModel):
    data: dict[str, Any]
    summary: ContextSummary


@register
class ContextManagerAgent(Agent):
    domain = "ai_core"
    name = "context_manager"
    description = (
        "Inspect a chat session: returns message count, approximate input "
        "token usage, and (when summarize=true) a Claude-generated paragraph "
        "summary of the conversation."
    )
    input_schema = ContextManagerInput
    output_schema = ContextManagerOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ContextManagerOutput:
        assert isinstance(payload, ContextManagerInput)
        try:
            sid = uuid.UUID(payload.session_id)
        except ValueError:
            raise AgentError("invalid_session_id", "session_id must be a UUID")

        session = await db.scalar(
            select(ConversationSession).where(
                ConversationSession.id == sid,
                ConversationSession.user_id == user.id,
            )
        )
        if session is None:
            raise AgentError(
                "session_not_found", f"No session with id {payload.session_id}."
            )

        rows = (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.session_id == sid)
                .order_by(ConversationMessage.created_at)
            )
        ).all()

        approx_tokens = sum(
            _approx_tokens(json.dumps(r.content, default=str)) for r in rows
        )

        summary_text: str | None = None
        if payload.summarize and rows:
            transcript = "\n".join(
                f"{r.role}: {json.dumps(r.content, default=str)}" for r in rows
            )[:32000]  # safety cap before sending to Claude
            msg = await ai.call(
                system=_SUMMARY_PROMPT,
                messages=[{"role": "user", "content": transcript}],
                max_tokens=300,
            )
            summary_text = "".join(
                block.get("text", "")
                for block in msg.get("content", [])
                if block.get("type") == "text"
            ).strip()

        return ContextManagerOutput(
            data={
                "model_used": (
                    os.getenv("ANTHROPIC_MODEL_DEFAULT", "claude-haiku-4-5-20251001")
                    if summary_text is not None
                    else None
                ),
                "messages_inspected": len(rows),
            },
            summary=ContextSummary(
                session_id=str(session.id),
                title=session.title,
                message_count=len(rows),
                approximate_tokens=approx_tokens,
                summary_text=summary_text,
            ),
        )
