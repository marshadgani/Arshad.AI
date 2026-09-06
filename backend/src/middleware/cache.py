import asyncio
import os

from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError(
        "REDIS_URL is not set. Copy backend/.env.example to backend/.env and fill it in."
    )

_redis: Redis | None = None
_init_lock = asyncio.Lock()


async def get_redis() -> Redis:
    global _redis
    if _redis is not None:
        return _redis
    async with _init_lock:
        if _redis is None:
            _redis = Redis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                # Without these, an unreachable host (dead DNS, dropped
                # network path) stalls on the OS-level TCP timeout — minutes,
                # not seconds — before any fail-open logic in a caller can
                # kick in. Redis is a cache dependency; callers should never
                # wait long for it.
                socket_connect_timeout=2,
                socket_timeout=2,
            )
    return _redis


async def close_redis() -> None:
    global _redis
    async with _init_lock:
        if _redis is not None:
            await _redis.aclose()
            _redis = None
