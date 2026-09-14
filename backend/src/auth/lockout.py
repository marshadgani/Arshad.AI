"""Per-email, fail-CLOSED brute-force lockout for password login.

Deliberately separate from ``middleware/rate_limit.py``'s shared fail-open
limiter — the two policies protect against different failure costs.
Losing volumetric rate limiting during a Redis outage degrades service;
losing this guard opens an unlimited-attempt window against a single
account. Per-IP rate limiting was evaluated and found not viable on the
deployed stack (see FEAT-143 system design, EV-1 / ADR-1), which makes
this per-email counter the entire brute-force defence for password
login — hence fail-CLOSED rather than fail-OPEN, per Arshad's explicit
2026-09-14 decision. Google/GitHub OAuth remains available as the login
fallback whenever this bucket denies a request (see
``backend/tests/test_auth_password.py::test_oauth_*_survives_redis_outage``
for the tested proof of that claim).
"""

from __future__ import annotations

import hashlib
import logging

import redis.exceptions

from ..api.errors import http_error
from ..middleware.cache import get_redis

_log = logging.getLogger(__name__)

_THRESHOLD = 5
_WINDOW_SECONDS = 900


def _bucket_key(email_norm: str) -> str:
    # The email is never stored in Redis in plaintext.
    digest = hashlib.sha256(email_norm.encode("utf-8")).hexdigest()
    return f"lk:{digest}"


async def assert_not_locked(email_norm: str) -> None:
    """Raise 429 if this email has failed too many times recently.

    Fails CLOSED on a Redis outage: raises 503 rather than letting an
    unreadable failure counter silently open an unlimited-attempt window.
    Uses a distinct status code and error code from the genuine-lockout
    429 (no ``Retry-After`` header, ERROR-level log) so a Redis outage is
    never mistaken for — or missed as — an active attack in Render's logs.
    """
    try:
        redis_client = await get_redis()
        raw = await redis_client.get(_bucket_key(email_norm))
    except redis.exceptions.RedisError as exc:
        _log.error(
            "Password-login lockout check unavailable — Redis unreachable: %s", exc
        )
        raise http_error(
            503,
            "login_temporarily_unavailable",
            "Password login is temporarily unavailable. Use Google or GitHub sign-in instead.",
        )

    count = int(raw) if raw else 0
    if count >= _THRESHOLD:
        raise http_error(
            429,
            "too_many_login_attempts",
            "Too many failed login attempts. Try again later.",
            details={"retry_after": _WINDOW_SECONDS},
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )


async def record_failure(email_norm: str) -> None:
    """Increment the failure counter for this email.

    Swallows RedisError: the request is already being rejected with 401
    on this path, and a Redis error here must not convert that clean 401
    into a 500 (which would itself leak that this branch differed).
    """
    try:
        redis_client = await get_redis()
        key = _bucket_key(email_norm)
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, _WINDOW_SECONDS, nx=True)
        await pipe.execute()
    except redis.exceptions.RedisError as exc:
        _log.warning(
            "Could not record password-login failure — Redis unreachable: %s", exc
        )


async def clear_failures(email_norm: str) -> None:
    """Reset the counter after a successful login.

    Swallows RedisError: a Redis blip on the success path must never 500
    an otherwise-valid login. Worst case the counter decays on its own TTL.
    """
    try:
        redis_client = await get_redis()
        await redis_client.delete(_bucket_key(email_norm))
    except redis.exceptions.RedisError as exc:
        _log.warning(
            "Could not clear password-login failures — Redis unreachable: %s", exc
        )


__all__ = ["assert_not_locked", "record_failure", "clear_failures"]
