"""In-process agent gateway.

Single entry point for both the REST router and Phase B chat. Inter-agent
calls (CLAUDE.md §19.4) MUST go through this function — never call
``Agent.run()`` directly. That keeps cross-cutting concerns (auth, error
mapping, observability) in one place.

Phase E shape: synchronous in-process call. Phase F may grow this into an
async-event-aware dispatcher; the public signature stays the same so
callers don't change.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.registry import AGENT_REGISTRY
from ..agents.registry import get as get_agent
from ..models.user import User


class GatewayError(Exception):
    """Wraps lookup / validation failures in the dispatcher."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


async def dispatch(
    domain: str,
    agent: str,
    *,
    user: User,
    db: AsyncSession,
    payload: dict,
) -> BaseModel:
    """Look up agent, validate payload, run, return.

    Raises:
        GatewayError(unknown_agent, 404) — slug not in registry
        GatewayError(invalid_input, 400) — payload fails Pydantic validation
        AgentError — bubbles up from the agent's run() so the router can
                     map .code to a status (e.g. not_yet_implemented -> 501).
    """
    instance = get_agent(domain, agent)
    if instance is None:
        raise GatewayError(
            "unknown_agent",
            f"No agent registered as '{domain}/{agent}'.",
            status=404,
        )
    try:
        validated = instance.input_schema.model_validate(payload)
    except ValidationError as exc:
        raise GatewayError(
            "invalid_input",
            f"Input failed validation for {domain}/{agent}.",
            status=400,
        ) from exc

    return await instance.run(user=user, db=db, payload=validated)


def list_agents() -> list[dict]:
    """Snapshot of every registered agent for the discovery endpoint."""
    return [
        {
            "domain": a.domain,
            "name": a.name,
            "slug": a.slug,
            "description": a.description,
            "input_schema": a.input_schema.model_json_schema(),
            "tool_dependencies": list(a.tool_dependencies),
        }
        for a in AGENT_REGISTRY.values()
    ]
