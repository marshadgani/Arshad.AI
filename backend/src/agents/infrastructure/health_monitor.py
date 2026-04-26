"""infrastructure/health_monitor — pings backing services.

Phase E: checks Postgres (SELECT 1), Redis (PING), and the presence of
the ANTHROPIC_API_KEY env var (cannot ping Anthropic without burning
budget — env var presence is the proxy).
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...middleware.cache import get_redis
from ...models.user import User
from ..base import Agent
from ..registry import register


class HealthMonitorInput(BaseModel):
    pass


class ComponentHealth(BaseModel):
    component: str
    ok: bool
    detail: str | None = None


class HealthSummary(BaseModel):
    ok: bool
    components: list[ComponentHealth]


class HealthMonitorOutput(BaseModel):
    data: dict[str, Any]
    summary: HealthSummary


async def _check_postgres(db: AsyncSession) -> ComponentHealth:
    try:
        await db.execute(text("SELECT 1"))
        return ComponentHealth(component="postgres", ok=True)
    except Exception as exc:
        return ComponentHealth(
            component="postgres", ok=False, detail=type(exc).__name__
        )


async def _check_redis() -> ComponentHealth:
    try:
        redis = await get_redis()
        pong = await redis.ping()
        return ComponentHealth(component="redis", ok=bool(pong))
    except Exception as exc:
        return ComponentHealth(component="redis", ok=False, detail=type(exc).__name__)


def _check_anthropic() -> ComponentHealth:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return ComponentHealth(component="anthropic", ok=False, detail="env var unset")
    if key.startswith("your-") or key == "":
        return ComponentHealth(component="anthropic", ok=False, detail="placeholder")
    return ComponentHealth(component="anthropic", ok=True)


@register
class HealthMonitorAgent(Agent):
    domain = "infrastructure"
    name = "health_monitor"
    description = (
        "Pings Postgres, Redis, and checks that ANTHROPIC_API_KEY is set "
        "to a non-placeholder value. Anthropic isn't pinged directly to "
        "avoid burning quota. Returns ok=False on any component failure."
    )
    input_schema = HealthMonitorInput
    output_schema = HealthMonitorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> HealthMonitorOutput:
        components = [
            await _check_postgres(db),
            await _check_redis(),
            _check_anthropic(),
        ]
        ok = all(c.ok for c in components)
        return HealthMonitorOutput(
            data={"components": [c.model_dump() for c in components]},
            summary=HealthSummary(ok=ok, components=components),
        )
