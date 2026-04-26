"""ai_core/context_manager — placeholder; needs conversation_messages table."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class ContextManagerInput(BaseModel):
    session_id: str = Field(min_length=1)
    max_tokens: int = Field(default=8000, ge=100, le=200_000)


class ContextSummary(BaseModel):
    session_id: str
    message_count: int
    estimated_tokens: int


class ContextManagerOutput(BaseModel):
    data: dict[str, Any]
    summary: ContextSummary


@register
class ContextManagerAgent(Agent):
    domain = "ai_core"
    name = "context_manager"
    description = (
        "Manages conversation history and context compression for chat. "
        "Phase E: not implemented — needs the conversation_messages table "
        "which Phase B introduces."
    )
    input_schema = ContextManagerInput
    output_schema = ContextManagerOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ContextManagerOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase B")
