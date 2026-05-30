"""ai_core/tool_dispatcher — runs an arbitrary Phase D tool by name.

This is the single agent that knows about Phase D's TOOL_REGISTRY. Phase
B's chat (Claude tool-use) will eventually call tools directly via the
registry, but in Phase E this agent provides a generic 'run any tool'
endpoint useful for ad-hoc curl testing and as a fallback the orchestrator
can fall back to.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.registry import TOOL_REGISTRY
from ..base import Agent, AgentError
from ..registry import register


class ToolDispatcherInput(BaseModel):
    tool_name: str = Field(min_length=1)
    payload: dict[str, Any]


class ToolDispatcherOutput(BaseModel):
    data: Any
    summary: Any


@register
class ToolDispatcherAgent(Agent):
    domain = "ai_core"
    name = "tool_dispatcher"
    description = (
        "Generic dispatcher: runs the named Phase D tool with the supplied "
        "payload. Useful for ad-hoc invocations and as a fallback path. "
        "Most callers should use the tool's REST endpoint directly."
    )
    input_schema = ToolDispatcherInput
    output_schema = ToolDispatcherOutput
    tool_dependencies: list[str] = []  # all tools — dynamic

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ToolDispatcherOutput:
        assert isinstance(payload, ToolDispatcherInput)
        tool = TOOL_REGISTRY.get(payload.tool_name)
        if tool is None:
            raise AgentError(
                "unknown_tool",
                f"No tool registered as '{payload.tool_name}'.",
            )
        try:
            validated = tool.input_schema.model_validate(payload.payload)
        except ValidationError as exc:
            raise AgentError(
                "invalid_input",
                f"Input failed validation for {payload.tool_name}: {exc.errors()[:3]}",
            )
        result = await tool(user=user, db=db, payload=validated)
        dumped = result.model_dump(mode="json")
        return ToolDispatcherOutput(
            data=dumped.get("data"),
            summary=dumped.get("summary"),
        )
