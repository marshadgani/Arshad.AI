"""The one place that knows *where* an Apple Health snapshot is kept.

Key format, TTL, envelope sealing, the bytes-vs-str decode of whatever
Redis hands back, and the read failure policy all live here. Before this
module those five facts were spread across three modules in two layers —
the router, the provider's sync(), and the provider's status() — each
re-deriving `redis.get(snapshot_cache_key(str(integration.id)))` for
itself. Changing the storage substrate meant finding all three.

Deliberately takes the Redis client as an argument rather than calling
get_redis() itself. The caller owns client acquisition, which keeps
get_redis patchable at the call site (see backend/tests/test_apple_health.py)
and makes every function here a pure function of its arguments.

The two readers differ on RedisError, deliberately:

    load()         absorbs it. Every reason a snapshot is unavailable
                   already collapses to None here (no push, TTL elapsed,
                   corrupt value, rotated key), so leaking a sixth outcome
                   would buy the always-visible dashboard path nothing but
                   an extra branch.
    has_snapshot() lets it out. Its caller
                   (AppleHealthIntegration._has_recent_push) owns the
                   "treat an outage as no recent push" decision and logs it
                   in the provider's own terms; hard-coding that here would
                   move a provider policy into the store.

Nothing here can observe a biometric value: it moves sealed envelopes
produced by envelope.py.
"""

from __future__ import annotations

import logging

import redis.exceptions
from redis.asyncio import Redis

from ...schemas.apple_health import AppleHealthSnapshot
from .envelope import decode_snapshot, encode_snapshot

_log = logging.getLogger(__name__)

# How long a pushed snapshot stays readable before the card reports itself
# stale. See the HUMAN REVIEW FLAG in integrations/personal/apple_health.py:
# a short-TTL cache is the closest available analogue to Whoop's
# fetch-live-per-request model for a push-only source that cannot be
# re-pulled between Shortcut runs.
CACHE_TTL_SECONDS = 6 * 60 * 60


def snapshot_cache_key(integration_id: str) -> str:
    """Redis key holding the latest pushed snapshot for one integration."""
    return f"apple_health:snapshot:{integration_id}"


async def write(
    redis_client: Redis, integration_id: str, snapshot: AppleHealthSnapshot
) -> None:
    """Seal and store a snapshot under its TTL.

    Raises RuntimeError when encryption is unavailable (OAUTH_ENCRYPTION_KEY
    missing/malformed) and redis.exceptions.RedisError when the store is
    unreachable. Both propagate: only the caller knows what HTTP status a
    failed write should become, and the two must stay distinguishable —
    "we could not encrypt" and "we could not store" have different fixes.
    """
    await redis_client.set(
        snapshot_cache_key(integration_id),
        encode_snapshot(snapshot),
        ex=CACHE_TTL_SECONDS,
    )


async def load(redis_client: Redis, integration_id: str) -> AppleHealthSnapshot | None:
    """Latest readable snapshot, or None.

    None covers every reason a snapshot is unavailable — no push yet, TTL
    elapsed, Redis unreachable, corrupt/foreign/legacy value, or a rotated
    encryption key — so the caller has exactly one miss branch to render.
    Never raises.
    """
    try:
        raw = await redis_client.get(snapshot_cache_key(integration_id))
    except redis.exceptions.RedisError:
        _log.warning(
            "apple_health.snapshot_store: Redis unavailable — treating as cache miss"
        )
        return None

    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return decode_snapshot(raw)


async def has_snapshot(redis_client: Redis, integration_id: str) -> bool:
    """Whether a push is still within the cache window.

    Does NOT decrypt: freshness is a property of the key existing, and an
    undecryptable value (post key-rotation) still proves the Shortcut ran.
    Lets RedisError propagate — see the module docstring.
    """
    return bool(await redis_client.get(snapshot_cache_key(integration_id)))
