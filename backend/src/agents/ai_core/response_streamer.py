"""ai_core/response_streamer — describes the SSE event protocol.

The actual streaming work lives in:
  - services/chat.py            (yields SSE-shaped strings)
  - api/v1/chat.py              (wraps in StreamingResponse)

This agent is the introspection endpoint. Calling it returns the event
schema so a frontend can validate against expected event shapes, or a
script can sanity-check that streaming is wired up before opening a
real session.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent
from ..registry import register


class ResponseStreamerInput(BaseModel):
    pass


class StreamerSummary(BaseModel):
    sse_endpoint: str
    media_type: str
    event_types: list[str]
    terminator: str


class ResponseStreamerOutput(BaseModel):
    data: dict[str, Any]
    summary: StreamerSummary


_EVENT_SHAPES: dict[str, dict[str, Any]] = {
    "intent": {"intent": "calendar | email | github | general"},
    "delta": {"delta": "<text chunk>"},
    "tool_use": {
        "tool_use": {
            "id": "<id>",
            "name": "<tool or agent_<slug>>",
            "input": "<input dict>",
        }
    },
    "tool_result": {
        "tool_result": {
            "id": "<id>",
            "name": "<tool name>",
            "output": "<output dict>",
            "is_error": "<bool>",
        }
    },
    "error": {"error": {"code": "<str>", "message": "<str>"}},
}


@register
class ResponseStreamerAgent(Agent):
    domain = "ai_core"
    name = "response_streamer"
    description = (
        "Returns the SSE event protocol used by the chat endpoint. "
        "Read-only introspection — actual streaming happens at "
        "POST /api/v1/chat/sessions/{id}/messages."
    )
    input_schema = ResponseStreamerInput
    output_schema = ResponseStreamerOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ResponseStreamerOutput:
        return ResponseStreamerOutput(
            data={"event_shapes": _EVENT_SHAPES},
            summary=StreamerSummary(
                sse_endpoint="/api/v1/chat/sessions/{id}/messages",
                media_type="text/event-stream",
                event_types=sorted(_EVENT_SHAPES.keys()),
                terminator="data: [DONE]\\n\\n",
            ),
        )
