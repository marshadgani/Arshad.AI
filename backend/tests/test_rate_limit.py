"""Direct unit tests for the sliding-window rate limiter.

Every call site in the codebase monkeypatches this module out, so its
core logic — the fail-open contract, the nx=True expire call shape, and
the 429 threshold — had zero direct coverage until these tests.

Mocking strategy: monkeypatch `get_redis` inside the rate_limit module
(same pattern used by test_auth.py for the routers_mod.get_redis swap).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.exceptions
from fastapi import HTTPException

import src.middleware.rate_limit as rate_limit_module
from src.middleware.rate_limit import enforce_rate_limit


# ── helpers ────────────────────────────────────────────────────────────────


def _make_pipeline(incr_return: int) -> tuple[MagicMock, MagicMock]:
    """Return (redis_client, pipeline) whose execute() yields (incr_return, True)."""
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[incr_return, True])

    redis_client = MagicMock()
    redis_client.pipeline = MagicMock(return_value=pipe)
    return redis_client, pipe


def _inject_redis(monkeypatch, redis_client: MagicMock) -> None:
    monkeypatch.setattr(
        rate_limit_module, "get_redis", AsyncMock(return_value=redis_client)
    )


# ── happy-path: requests within the window ────────────────────────────────


@pytest.mark.asyncio
async def test_first_request_in_window_does_not_raise(monkeypatch):
    redis_client, _ = _make_pipeline(incr_return=1)
    _inject_redis(monkeypatch, redis_client)

    await enforce_rate_limit(
        bucket="test", identity="user1", limit=5, window_seconds=60, message="too many"
    )


@pytest.mark.asyncio
async def test_request_exactly_at_limit_does_not_raise(monkeypatch):
    redis_client, _ = _make_pipeline(incr_return=5)
    _inject_redis(monkeypatch, redis_client)

    await enforce_rate_limit(
        bucket="test", identity="user1", limit=5, window_seconds=60, message="too many"
    )


# ── threshold: one over the limit is rejected ─────────────────────────────


@pytest.mark.asyncio
async def test_request_one_over_limit_raises_429(monkeypatch):
    redis_client, _ = _make_pipeline(incr_return=6)
    _inject_redis(monkeypatch, redis_client)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(
            bucket="test",
            identity="user1",
            limit=5,
            window_seconds=60,
            message="too many",
        )

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_429_response_carries_standard_error_envelope(monkeypatch):
    redis_client, _ = _make_pipeline(incr_return=99)
    _inject_redis(monkeypatch, redis_client)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(
            bucket="test",
            identity="user1",
            limit=5,
            window_seconds=60,
            message="too many",
        )

    assert exc_info.value.detail["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_429_response_includes_retry_after_header(monkeypatch):
    redis_client, _ = _make_pipeline(incr_return=99)
    _inject_redis(monkeypatch, redis_client)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(
            bucket="test",
            identity="user1",
            limit=5,
            window_seconds=120,
            message="too many",
        )

    assert exc_info.value.headers == {"Retry-After": "120"}


# ── fail-open: Redis outage must NOT block the request ─────────────────────


@pytest.mark.asyncio
async def test_redis_error_on_pipeline_execute_fails_open(monkeypatch):
    """Regression guard: a Redis outage degrades rate limiting rather than
    taking the dependent endpoint down with it (Property 1 in the module docstring).
    """
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(
        side_effect=redis.exceptions.RedisError("connection refused")
    )

    redis_client = MagicMock()
    redis_client.pipeline = MagicMock(return_value=pipe)
    _inject_redis(monkeypatch, redis_client)

    # Must return silently — must NOT raise
    await enforce_rate_limit(
        bucket="test", identity="user1", limit=5, window_seconds=60, message="too many"
    )


@pytest.mark.asyncio
async def test_redis_connection_error_subclass_also_fails_open(monkeypatch):
    """ConnectionError is a subclass of RedisError — the catch block covers it."""
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(
        side_effect=redis.exceptions.ConnectionError("timed out")
    )

    redis_client = MagicMock()
    redis_client.pipeline = MagicMock(return_value=pipe)
    _inject_redis(monkeypatch, redis_client)

    await enforce_rate_limit(
        bucket="test", identity="user1", limit=5, window_seconds=60, message="too many"
    )


# ── call-shape: expire(key, window, nx=True) ─────────────────────────────


@pytest.mark.asyncio
async def test_expire_is_called_with_nx_true(monkeypatch):
    """Regression guard: expire MUST be called with nx=True.

    Without nx=True the TTL-repair is not idempotent: if incr succeeds but
    expire fails, the key has no TTL forever. Every subsequent call sees a
    counter already above the limit and the caller is permanently locked out
    rather than the outage failing open (Property 2 in the module docstring).
    """
    redis_client, pipe = _make_pipeline(incr_return=1)
    _inject_redis(monkeypatch, redis_client)

    await enforce_rate_limit(
        bucket="applehealth",
        identity="integration-abc",
        limit=20,
        window_seconds=3600,
        message="too many",
    )

    pipe.expire.assert_called_once_with("rl:applehealth:integration-abc", 3600, nx=True)


@pytest.mark.asyncio
async def test_expire_window_matches_the_configured_window_seconds(monkeypatch):
    redis_client, pipe = _make_pipeline(incr_return=1)
    _inject_redis(monkeypatch, redis_client)

    await enforce_rate_limit(
        bucket="whoop",
        identity="user-xyz",
        limit=30,
        window_seconds=60,
        message="too many",
    )

    _, window_arg, *_ = pipe.expire.call_args.args
    assert window_arg == 60


# ── key namespacing ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_incr_key_follows_rl_bucket_identity_pattern(monkeypatch):
    redis_client, pipe = _make_pipeline(incr_return=1)
    _inject_redis(monkeypatch, redis_client)

    await enforce_rate_limit(
        bucket="whoop",
        identity="user-xyz",
        limit=30,
        window_seconds=60,
        message="too many",
    )

    pipe.incr.assert_called_once_with("rl:whoop:user-xyz")


@pytest.mark.asyncio
async def test_different_buckets_produce_different_keys(monkeypatch):
    """Two concurrent rate limiters with different buckets must not share state."""
    redis_client_a, pipe_a = _make_pipeline(incr_return=1)
    redis_client_b, pipe_b = _make_pipeline(incr_return=1)

    calls: list[str] = []

    async def _get_redis_spy() -> MagicMock:
        # return a fresh client on each call so we can see each bucket's key
        rc, pipe = _make_pipeline(1)
        pipe.incr = MagicMock(side_effect=lambda k: calls.append(k))
        return rc

    monkeypatch.setattr(rate_limit_module, "get_redis", _get_redis_spy)

    await enforce_rate_limit(
        bucket="whoop", identity="u1", limit=30, window_seconds=60, message="too many"
    )
    await enforce_rate_limit(
        bucket="applehealth", identity="u1", limit=20, window_seconds=3600, message="too many"
    )

    assert "rl:whoop:u1" in calls
    assert "rl:applehealth:u1" in calls
    assert len(set(calls)) == 2
