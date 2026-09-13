"""Fail-open Redis cache for the dashboard weather tile.

Separate from ``service.py`` so the OpenWeatherMap provider can invalidate
the cache after it rewrites ``integration.config['city']`` without
importing the service that imports the provider (circular). Same split,
and the same fail-open contract, as ``services/shopify/cache.py``.

Every call is wrapped: a Redis outage degrades caching, not the tile.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.exceptions

from ...middleware.cache import get_redis

_log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 600


def cache_key(integration_id: str) -> str:
    return f"weather:{integration_id}"


async def get_cached(integration_id: str) -> dict[str, Any] | None:
    try:
        redis_client = await get_redis()
        raw = await redis_client.get(cache_key(integration_id))
    except redis.exceptions.RedisError as exc:
        _log.warning("Weather cache read degraded — Redis unreachable: %s", exc)
        return None
    if not raw:
        return None
    # A cache entry is data, not a contract: anything that is not a JSON
    # object (corrupt, or written by an older shape of the parser) is
    # discarded so the caller re-fetches upstream.
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        _log.warning(
            "Weather cache entry for %s is not a JSON object — discarding "
            "and re-fetching upstream.",
            integration_id,
        )
        return None
    return payload


async def set_cached(integration_id: str, data: dict[str, Any]) -> None:
    try:
        redis_client = await get_redis()
        await redis_client.set(
            cache_key(integration_id), json.dumps(data), ex=CACHE_TTL_SECONDS
        )
    except redis.exceptions.RedisError as exc:
        _log.warning("Weather cache write degraded — Redis unreachable: %s", exc)


async def del_cached(integration_id: str) -> None:
    """Drop the cached tile — call after anything the tile renders changes.

    The cache key is the integration id, and ``store_api_key()`` upserts
    the SAME integration row on reconnect, so a user who reconnects with a
    different city keeps their old city's id. Without this the dashboard
    serves the previous city for up to ``CACHE_TTL_SECONDS``.
    """
    try:
        redis_client = await get_redis()
        await redis_client.delete(cache_key(integration_id))
    except redis.exceptions.RedisError as exc:
        _log.warning("Weather cache delete degraded — Redis unreachable: %s", exc)
