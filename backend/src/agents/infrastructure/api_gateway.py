"""infrastructure/api_gateway — self-reflective view of the gateway.

This agent is a self-reference: ``services/gateway.py`` IS the API
gateway. The agent exposes a read-only snapshot of the registered
domains + per-domain agent counts so the frontend health widget can
display 'how many agents are alive in each domain'.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent
from ..registry import AGENT_REGISTRY, register


class ApiGatewayInput(BaseModel):
    pass  # no input


class DomainSnapshot(BaseModel):
    domain: str
    agent_count: int
    agents: list[str]


class ApiGatewaySummary(BaseModel):
    total_agents: int
    domains: list[DomainSnapshot]


class ApiGatewayOutput(BaseModel):
    data: dict[str, Any]
    summary: ApiGatewaySummary


@register
class ApiGatewayAgent(Agent):
    domain = "infrastructure"
    name = "api_gateway"
    description = (
        "Returns a snapshot of the gateway: how many agents are registered "
        "per domain. Self-reference — services/gateway.py IS the gateway, "
        "this agent provides a read-only introspection endpoint."
    )
    input_schema = ApiGatewayInput
    output_schema = ApiGatewayOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ApiGatewayOutput:
        per_domain: dict[str, list[str]] = {}
        for slug, agent in AGENT_REGISTRY.items():
            per_domain.setdefault(agent.domain, []).append(agent.name)
        snapshots = [
            DomainSnapshot(domain=d, agent_count=len(names), agents=sorted(names))
            for d, names in sorted(per_domain.items())
        ]
        counts = Counter(a.domain for a in AGENT_REGISTRY.values())
        return ApiGatewayOutput(
            data={"per_domain_counts": dict(counts)},
            summary=ApiGatewaySummary(
                total_agents=len(AGENT_REGISTRY), domains=snapshots
            ),
        )
