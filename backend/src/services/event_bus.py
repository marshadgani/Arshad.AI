"""Redis pub/sub primitives for cross-agent async events.

Phase F use: ingestors publish ``events.<provider>.ingested`` after each
batch. Phase B chat (and any future agent) can subscribe later. We don't
persist events — Redis pub/sub is fire-and-forget; subscribers must be
running at publish time.

For at-least-once delivery use a streams-backed pattern instead — not
needed in Phase F since the consumers are still TBD.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ..middleware.cache import get_redis


async def publish(channel: str, payload: dict[str, Any]) -> int:
    """Returns the count of subscribers that received the message."""
    redis = await get_redis()
    return await redis.publish(channel, json.dumps(payload, default=str))


async def subscribe(*channels: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Async iterator yielding (channel, payload) tuples.

    Caller is responsible for canceling the iteration on shutdown — the
    underlying Redis connection stays open while listening. Wrap in a
    task that the lifespan can cancel.
    """
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(*channels)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            channel = message.get("channel", "")
            data = message.get("data", "")
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            yield channel, payload
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
