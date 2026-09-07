"""Fail-open Redis cache for the Shopify dashboard response.

120s TTL matches the frontend's poll interval, bounding steady-state
upstream cost regardless of tab count or refresh spamming. Every call is
wrapped so a Redis outage degrades caching, not the page — mirrors
src/middleware/rate_limit.py's fail-open property.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.exceptions

from ...middleware.cache import get_redis

_log = logging.getLogger(__name__)

DASHBOARD_TTL_SECONDS = 120


def dashboard_cache_key(integration_id: str) -> str:
    return f"shopify:dash:{integration_id}"


async def get_cached_dashboard(integration_id: str) -> dict[str, Any] | None:
    try:
        redis_client = await get_redis()
        raw = await redis_client.get(dashboard_cache_key(integration_id))
    except redis.exceptions.RedisError as exc:
        _log.warning("Shopify dashboard cache read failed: %s", exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def set_cached_dashboard(
    integration_id: str, data: dict[str, Any], ttl: int = DASHBOARD_TTL_SECONDS
) -> None:
    try:
        redis_client = await get_redis()
        await redis_client.set(
            dashboard_cache_key(integration_id), json.dumps(data), ex=ttl
        )
    except redis.exceptions.RedisError as exc:
        _log.warning("Shopify dashboard cache write failed: %s", exc)


async def del_dashboard_cache(integration_id: str) -> None:
    try:
        redis_client = await get_redis()
        await redis_client.delete(dashboard_cache_key(integration_id))
    except redis.exceptions.RedisError as exc:
        _log.warning("Shopify dashboard cache delete failed: %s", exc)
