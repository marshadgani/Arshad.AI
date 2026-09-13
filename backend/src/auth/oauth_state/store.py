"""Redis-backed, single-use store for in-flight login state.

Owns two things and nothing else: the key namespace, and the fail-closed
contract. It never decides an HTTP status — it raises
`LoginStateUnavailable` and lets the caller (which owns the HTTP layer)
translate that into the 503 envelope. That split is what lets the
"a Redis outage must never silently skip the CSRF check" rule live in
exactly one place instead of being re-asserted at every call site.

The Redis client is passed in rather than imported so the connection
seam stays with the caller — the store has no opinion on how the client
is obtained or pooled.
"""

from __future__ import annotations

from redis.exceptions import RedisError

#: Anything that can mean "Redis did not answer". Deliberately wide:
#: every member of it must fail the login closed, never open.
REDIS_ERRORS = (RedisError, ConnectionError, TimeoutError, OSError)


class LoginStateUnavailable(RuntimeError):
    """Redis was unreachable while reading/writing login state.

    Carries the phase (`set` / `getdel`) so the caller can log which leg
    of the round trip failed without re-deriving it from a traceback.
    """

    def __init__(self, phase: str, cause: BaseException) -> None:
        super().__init__(f"login state store unavailable during {phase}")
        self.phase = phase
        self.cause = cause


def login_nonce_key(nonce: str) -> str:
    return f"login_oauth_state:{nonce}"


async def put_state(redis, nonce: str, value: str, *, ttl: int) -> None:
    """Record an in-flight login attempt. Raises LoginStateUnavailable."""
    try:
        await redis.set(login_nonce_key(nonce), value, ex=ttl)
    except REDIS_ERRORS as exc:
        raise LoginStateUnavailable("set", exc) from exc


async def take_state(redis, nonce: str) -> str | None:
    """Atomically read-and-delete the attempt; None if already used/expired.

    GETDEL (not GET) is what makes a state single-use: two concurrent
    callbacks for one state cannot both see a value, so a captured
    `code`+`state` pair can never be replayed.
    """
    try:
        return await redis.getdel(login_nonce_key(nonce))
    except REDIS_ERRORS as exc:
        raise LoginStateUnavailable("getdel", exc) from exc
