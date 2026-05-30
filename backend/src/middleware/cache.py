import asyncio
import os

from redis.asyncio import Redis

_redis: Redis | None = None
_init_lock = asyncio.Lock()


def _redis_url() -> str:
    url = os.getenv("REDIS_URL")
    if not url:
        raise RuntimeError(
            "REDIS_URL is not set. Copy backend/.env.example to backend/.env and fill it in."
        )
    return url


async def get_redis() -> Redis:
    global _redis
    if _redis is not None:
        return _redis
    async with _init_lock:
        if _redis is None:
            _redis = Redis.from_url(
                _redis_url(),
                encoding="utf-8",
                decode_responses=True,
            )
    return _redis


async def close_redis() -> None:
    global _redis
    async with _init_lock:
        if _redis is not None:
            await _redis.aclose()
            _redis = None
