"""Redis advisory lock guarding a user's export run.

Isolated from the orchestrator because its correctness rests on a
distinction that is easy to lose in a longer function: *acquired* (this
call may proceed) is not the same as *held* (this call owns the key and
must release it). When Redis is unreachable the run proceeds anyway —
the GitHub ref fast-forward is the real backstop against two concurrent
writers — but it must not then delete a key that a genuinely concurrent
run is holding.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ...middleware.cache import get_redis

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 900


def _lock_key(user_id: uuid.UUID) -> str:
    return f"obsidian:export:{user_id}"


@asynccontextmanager
async def export_lock(user_id: uuid.UUID) -> AsyncIterator[bool]:
    """Yield True when the caller may run the export, False when another
    run already holds the lock.

    Releases the key on exit only if this call actually took it.
    """
    redis = None
    held = False  # True only when *this* call won the SET NX
    acquired = False
    key = _lock_key(user_id)
    try:
        redis = await get_redis()
        held = bool(await redis.set(key, "1", nx=True, ex=LOCK_TTL_SECONDS))
        acquired = held
    except Exception as exc:  # noqa: BLE001 — Redis is never load-bearing here
        logger.warning("obsidian_export: redis lock unavailable — %s", exc)
        acquired = True  # fail-open on the lock; ref PATCH is the backstop

    try:
        yield acquired
    finally:
        # Only release a lock this call actually took. On the fail-open path
        # (redis.set raised after the client was created) the key may belong
        # to a concurrently running export — deleting it there would hand a
        # second writer the go-ahead mid-run.
        if redis is not None and held:
            try:
                await redis.delete(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("obsidian_export: failed to release lock — %s", exc)


__all__ = ["LOCK_TTL_SECONDS", "export_lock"]
