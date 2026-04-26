"""ai_core/response_streamer — placeholder; SSE plumbing lands in Phase B."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class ResponseStreamerInput(BaseModel):
    session_id: str = Field(min_length=1)


class ResponseStreamerOutput(BaseModel):
    data: dict[str, Any]
    summary: dict[str, Any]


@register
class ResponseStreamerAgent(Agent):
    domain = "ai_core"
    name = "response_streamer"
    description = (
        "Handles SSE streaming of Claude responses to the frontend. "
        "Phase E: not implemented — Phase B lands the StreamingResponse "
        "wiring + chunk-event protocol."
    )
    input_schema = ResponseStreamerInput
    output_schema = ResponseStreamerOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ResponseStreamerOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase B")
