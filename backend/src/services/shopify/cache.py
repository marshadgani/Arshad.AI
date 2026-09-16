"""Fail-open Redis cache for Shopify read models (dashboard + insights).

Every call is wrapped so a Redis outage degrades caching, not the page —
mirrors src/middleware/rate_limit.py's fail-open property. The get/set/
delete try/except blocks live exactly once, in the private `_cache_*`
helpers below; every public function delegates to them instead of
re-declaring the same RedisError handling.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.exceptions

from ...middleware.cache import get_redis

_log = logging.getLogger(__name__)

# 120s matches the frontend's dashboard poll interval, bounding steady-state
# upstream cost regardless of tab count or refresh spamming.
DASHBOARD_TTL_SECONDS = 120

# Insights is daily-granularity data — nothing meaningfully changes inside
# 15 minutes except today's still-accumulating partial day. 900s caps the
# endpoint at 4 upstream fetch cycles/hour/day-variant, which keeps the
# worst case comfortably inside the shop's leaky bucket alongside the
# dashboard's own 120s cycle.
INSIGHTS_TTL_SECONDS = 900

# The only `days` values the /insights route accepts — see api/v1/shopify.py.
# Enumerated here (not imported from there, to avoid a router->service
# import) so del_insights_cache can remove every variant on invalidation.
INSIGHTS_DAY_VARIANTS = (7, 14, 30)


async def _cache_get(key: str) -> dict[str, Any] | None:
    try:
        redis_client = await get_redis()
        raw = await redis_client.get(key)
    except redis.exceptions.RedisError as exc:
        _log.warning("Shopify cache read failed key=%s: %s", key, exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def _cache_set(key: str, data: dict[str, Any], ttl: int) -> None:
    try:
        redis_client = await get_redis()
        await redis_client.set(key, json.dumps(data), ex=ttl)
    except redis.exceptions.RedisError as exc:
        _log.warning("Shopify cache write failed key=%s: %s", key, exc)


async def _cache_del(*keys: str) -> None:
    try:
        redis_client = await get_redis()
        await redis_client.delete(*keys)
    except redis.exceptions.RedisError as exc:
        _log.warning("Shopify cache delete failed keys=%s: %s", keys, exc)


# ── Dashboard ──────────────────────────────────────────────────────────────


def dashboard_cache_key(integration_id: str) -> str:
    return f"shopify:dash:{integration_id}"


async def get_cached_dashboard(integration_id: str) -> dict[str, Any] | None:
    return await _cache_get(dashboard_cache_key(integration_id))


async def set_cached_dashboard(
    integration_id: str, data: dict[str, Any], ttl: int = DASHBOARD_TTL_SECONDS
) -> None:
    await _cache_set(dashboard_cache_key(integration_id), data, ttl)


async def del_dashboard_cache(integration_id: str) -> None:
    await _cache_del(dashboard_cache_key(integration_id))


# ── Insights (FEAT-159) ──────────────────────────────────────────────────
#
# `days` is part of the key — a 14-day payload must never be served to a
# 30-day request, so each window size gets its own cache entry.


def insights_cache_key(integration_id: str, days: int) -> str:
    return f"shopify:insights:{integration_id}:{days}"


async def get_cached_insights(integration_id: str, days: int) -> dict[str, Any] | None:
    return await _cache_get(insights_cache_key(integration_id, days))


async def set_cached_insights(
    integration_id: str, days: int, data: dict[str, Any]
) -> None:
    await _cache_set(
        insights_cache_key(integration_id, days), data, INSIGHTS_TTL_SECONDS
    )


async def del_insights_cache(integration_id: str) -> None:
    """Remove every day-variant of a store's cached insights.

    Wired into the same metadata-refresh / reconnect path that already
    calls del_dashboard_cache, so a re-linked store never serves the prior
    store's trend, and a shop-timezone change never leaves a stale bucketing
    behind it.
    """
    await _cache_del(
        *(insights_cache_key(integration_id, days) for days in INSIGHTS_DAY_VARIANTS)
    )
