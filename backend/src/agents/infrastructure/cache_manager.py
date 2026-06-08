"""infrastructure/cache_manager — namespaced Redis CRUD.

Each user gets a private prefix (`agent_cache:{user_id}:{key}`) so
agents can stash short-lived state without colliding across users.
TTL bounded to 1 day to prevent unbounded growth.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...middleware.cache import get_redis
from ...models.user import User
from ..base import Agent, AgentError
from ..registry import register

_MAX_TTL = 24 * 60 * 60


class CacheManagerInput(BaseModel):
    action: Literal["get", "set", "delete"]
    key: str = Field(min_length=1, max_length=128)
    value: str | None = None
    ttl_seconds: int | None = Field(default=None, ge=1, le=_MAX_TTL)

    @model_validator(mode="after")
    def _set_needs_value(self) -> "CacheManagerInput":
        if self.action == "set" and self.value is None:
            raise ValueError("action='set' requires value")
        return self


class CacheSummary(BaseModel):
    action: str
    key: str
    hit: bool
    value: str | None = None


class CacheManagerOutput(BaseModel):
    data: dict[str, Any]
    summary: CacheSummary


@register
class CacheManagerAgent(Agent):
    domain = "infrastructure"
    name = "cache_manager"
    description = (
        "Per-user namespaced Redis CRUD on agent_cache:{user_id}:{key}. "
        "TTL capped at 24h. Useful for agents that need to memoise the "
        "result of an expensive Phase D tool call across requests."
    )
    input_schema = CacheManagerInput
    output_schema = CacheManagerOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CacheManagerOutput:
        assert isinstance(payload, CacheManagerInput)
        redis = await get_redis()
        full_key = f"agent_cache:{user.id}:{payload.key}"

        if payload.action == "get":
            value = await redis.get(full_key)
            return CacheManagerOutput(
                data={"key": full_key, "value": value},
                summary=CacheSummary(
                    action="get", key=payload.key, hit=value is not None, value=value
                ),
            )
        if payload.action == "set":
            assert payload.value is not None  # validator
            ttl = payload.ttl_seconds or _MAX_TTL
            await redis.set(full_key, payload.value, ex=ttl)
            return CacheManagerOutput(
                data={"key": full_key, "ttl": ttl},
                summary=CacheSummary(
                    action="set", key=payload.key, hit=True, value=payload.value
                ),
            )
        if payload.action == "delete":
            removed = await redis.delete(full_key)
            return CacheManagerOutput(
                data={"key": full_key, "removed": removed},
                summary=CacheSummary(
                    action="delete", key=payload.key, hit=bool(removed)
                ),
            )
        raise AgentError("invalid_action", f"Unknown action: {payload.action}")
