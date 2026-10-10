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
from fastapi import HTTPException

from ..api.errors import http_error
from .cache import get_redis

_log = logging.getLogger(__name__)


class RateLimitExceeded(HTTPException):
    """HTTPException(429) with the standard error envelope.

    `enforce_rate_limit` raises ``HTTPException`` via ``http_error``; this
    subclass exists so tests can inject a 429 via
    ``monkeypatch.setattr(..., AsyncMock(side_effect=RateLimitExceeded(...)))``
    without constructing a bare ``HTTPException`` manually.  The detail
    structure is identical to what ``http_error(429, ...)`` produces, so
    ``main.py``'s ``http_exception_handler`` returns ``{"error": {...}}`` with
    status 429 in both cases.
    """

    def __init__(self, bucket: str, limit: int, window_seconds: int) -> None:
        super().__init__(
            status_code=429,
            detail={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": (
                        f"Rate limit exceeded for {bucket!r}: "
                        f"max {limit} requests per {window_seconds}s."
                    ),
                    "details": {"retry_after": window_seconds},
                }
            },
            headers={"Retry-After": str(window_seconds)},
        )


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
        # incr + expire(nx=True) as one pipelined round trip instead of two
        # sequential awaits — halves the Redis latency this check adds to
        # every Whoop and Apple Health request (each Health page load fires
        # it 2-3 times). Pipeline preserves the fail-open contract: any
        # error in either command still raises RedisError from execute()
        # and is caught below exactly as it was for two separate calls.
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = await pipe.execute()
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
