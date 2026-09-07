"""Shared fail-open Redis sliding-window rate limiter.

Whoop (30/min per user) and Apple Health ingest (20/hour per integration)
each carried a byte-for-byte identical copy of this logic with different
constants. The duplication meant the two subtle correctness properties
below had to be re-derived — and could silently drift — per call site.

Property 1 — fails open. A Redis outage degrades rate limiting rather than
taking the dependent endpoint down with it. Losing rate limiting is
recoverable; losing the Health & Fitness page or the only ingest path over
a cache dependency is not.

Property 2 — the expire is unconditional with nx=True, NOT guarded by
`if count == 1`. A transient error between a successful incr and its expire
would otherwise leave the key with no TTL forever: once the counter climbed
past the limit the caller would be locked out permanently instead of the
outage failing open. nx=True makes the repair idempotent — it sets the TTL
only when one is missing, so the window is never extended by later calls.
"""

from __future__ import annotations

import logging

import redis.exceptions

from ..api.errors import http_error
from .cache import get_redis

_log = logging.getLogger(__name__)


async def enforce_rate_limit(
    *,
    bucket: str,
    identity: str,
    limit: int,
    window_seconds: int,
    message: str,
) -> None:
    """Count one hit against `rl:{bucket}:{identity}`; raise 429 past `limit`.

    Raises HTTPException(429) with the standard error envelope and a
    Retry-After header. Returns silently when Redis is unreachable.
    """
    try:
        redis_client = await get_redis()
        key = f"rl:{bucket}:{identity}"
        count = await redis_client.incr(key)
        await redis_client.expire(key, window_seconds, nx=True)
    except redis.exceptions.RedisError as exc:
        _log.warning(
            "Rate limiter degraded for bucket %s — Redis unreachable: %s", bucket, exc
        )
        return

    if count > limit:
        raise http_error(
            429,
            "rate_limit_exceeded",
            message,
            details={"retry_after": window_seconds},
            headers={"Retry-After": str(window_seconds)},
        )
