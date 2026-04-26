"""ai_core/chat_orchestrator — drives one chat turn synchronously.

Phase B: real implementation. The streaming entry point is the REST
endpoint POST /api/v1/chat/sessions/{id}/messages — that's the path
the frontend uses for live SSE. This agent endpoint is the SYNCHRONOUS
fallback: it consumes the same chat_turn() iterator but accumulates
events into a single response payload.

Useful for ad-hoc curl testing and for callers (other agents, scripts)
that want chat behavior without dealing with SSE.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.conversation import ConversationSession
from ...models.user import User
from ...services import chat as chat_service
from ..base import Agent, AgentError
from ..registry import register


class ChatOrchestratorInput(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    session_id: str | None = Field(
        default=None,
        description="Existing session UUID. Omit to create a new session for this turn.",
    )


class ChatOrchestratorSummary(BaseModel):
    session_id: str
    intent: str | None
    assistant_text: str
    tool_calls: list[dict[str, Any]]


class ChatOrchestratorOutput(BaseModel):
    data: dict[str, Any]
    summary: ChatOrchestratorSummary


def _parse_sse_payload(line: str) -> dict[str, Any] | None:
    if not line.startswith("data: "):
        return None
    body = line[len("data: ") :].strip()
    if body == "[DONE]":
        return {"_done": True}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


@register
class ChatOrchestratorAgent(Agent):
    domain = "ai_core"
    name = "chat_orchestrator"
    description = (
        "Synchronous chat: send a user message, get the full assistant "
        "response back as a single payload. The streaming counterpart is "
        "POST /api/v1/chat/sessions/{id}/messages (SSE)."
    )
    input_schema = ChatOrchestratorInput
    output_schema = ChatOrchestratorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ChatOrchestratorOutput:
        assert isinstance(payload, ChatOrchestratorInput)

        if payload.session_id:
            import uuid

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
                    "session_not_found",
                    f"No chat session with id {payload.session_id}.",
                )
        else:
            session = ConversationSession(user_id=user.id, title="New chat")
            db.add(session)
            await db.commit()
            await db.refresh(session)

        intent: str | None = None
        assistant_text = ""
        tool_calls: list[dict[str, Any]] = []
        all_events: list[dict[str, Any]] = []

        async for sse_chunk in chat_service.chat_turn(
            session=session, user=user, db=db, user_text=payload.text
        ):
            for line in sse_chunk.splitlines():
                event = _parse_sse_payload(line)
                if event is None:
                    continue
                if event.get("_done"):
                    continue
                all_events.append(event)
                if "intent" in event:
                    intent = event["intent"]
                if "delta" in event:
                    assistant_text += event["delta"]
                if "tool_use" in event:
                    tool_calls.append({"event": "tool_use", **event["tool_use"]})
                if "tool_result" in event:
                    tool_calls.append({"event": "tool_result", **event["tool_result"]})

        return ChatOrchestratorOutput(
            data={"session_id": str(session.id), "events": all_events},
            summary=ChatOrchestratorSummary(
                session_id=str(session.id),
                intent=intent,
                assistant_text=assistant_text,
                tool_calls=tool_calls,
            ),
        )
