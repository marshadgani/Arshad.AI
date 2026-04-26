"""ai_core/chat_orchestrator — placeholder; Phase B owns intent routing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class ChatOrchestratorInput(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatOrchestratorOutput(BaseModel):
    data: dict[str, Any]
    summary: dict[str, Any]


@register
class ChatOrchestratorAgent(Agent):
    domain = "ai_core"
    name = "chat_orchestrator"
    description = (
        "Routes user chat messages to the appropriate domain agent via the "
        "gateway. Phase E: not implemented — Phase B will wire Claude tool-use "
        "to pick the right agent and stream the response back."
    )
    input_schema = ChatOrchestratorInput
    output_schema = ChatOrchestratorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ChatOrchestratorOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase B")
