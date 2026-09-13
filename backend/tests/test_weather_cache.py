"""Unit tests for backend/src/services/weather/cache.py.

Redis is replaced by an AsyncMock so no real instance is needed.

The contract under test is fail-open: this cache backs an always-HTTP-200
tile, so every Redis failure must degrade caching and nothing else. A
RedisError escaping any of these three functions would reach service.py's
generic handler and render a degraded tile for a fault that has nothing to
do with the weather.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import redis.exceptions

from backend.src.services.weather.cache import (
    CACHE_TTL_SECONDS,
    cache_key,
    del_cached,
    get_cached,
    set_cached,
)

_INTEGRATION_ID = "aaaaaaaa-0000-0000-0000-000000000001"


def _patch_redis(client: AsyncMock):
    return patch(
        "backend.src.services.weather.cache.get_redis",
        AsyncMock(return_value=client),
    )


# ---------------------------------------------------------------------------
# Key and TTL
# ---------------------------------------------------------------------------


def test_cache_key_is_namespaced_by_integration_id():
    assert cache_key(_INTEGRATION_ID) == f"weather:{_INTEGRATION_ID}"


def test_cache_ttl_is_ten_minutes():
    assert CACHE_TTL_SECONDS == 600


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_then_get_round_trips():
    store: dict[str, str] = {}
    client = AsyncMock()
    client.set = AsyncMock(side_effect=lambda k, v, ex: store.__setitem__(k, v))
    client.get = AsyncMock(side_effect=lambda k: store.get(k))

    payload = {"temp": "15 °C", "condition": "Clouds", "city": "London"}
    with _patch_redis(client):
        await set_cached(_INTEGRATION_ID, payload)
        assert await get_cached(_INTEGRATION_ID) == payload


@pytest.mark.asyncio
async def test_set_cached_applies_the_ttl():
    client = AsyncMock()
    with _patch_redis(client):
        await set_cached(_INTEGRATION_ID, {"temp": "15 °C"})

    _, kwargs = client.set.call_args
    assert kwargs["ex"] == CACHE_TTL_SECONDS


@pytest.mark.asyncio
async def test_get_cached_returns_none_on_miss():
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    with _patch_redis(client):
        assert await get_cached(_INTEGRATION_ID) is None


# ---------------------------------------------------------------------------
# Untrusted entries are discarded, never raised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_json_entry_is_discarded():
    client = AsyncMock()
    client.get = AsyncMock(return_value=b"not valid json {{")
    with _patch_redis(client):
        assert await get_cached(_INTEGRATION_ID) is None


@pytest.mark.asyncio
async def test_json_non_object_entry_is_discarded():
    """A JSON list is parseable but is not the shape from_cache reads."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=json.dumps(["not", "a", "dict"]).encode())
    with _patch_redis(client):
        assert await get_cached(_INTEGRATION_ID) is None


@pytest.mark.asyncio
async def test_empty_entry_is_treated_as_a_miss():
    client = AsyncMock()
    client.get = AsyncMock(return_value=b"")
    with _patch_redis(client):
        assert await get_cached(_INTEGRATION_ID) is None


# ---------------------------------------------------------------------------
# Fail-open on Redis outage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cached_fails_open():
    client = AsyncMock()
    client.get = AsyncMock(
        side_effect=redis.exceptions.ConnectionError("Connection refused")
    )
    with _patch_redis(client):
        assert await get_cached(_INTEGRATION_ID) is None


@pytest.mark.asyncio
async def test_set_cached_fails_open():
    client = AsyncMock()
    client.set = AsyncMock(
        side_effect=redis.exceptions.ConnectionError("Connection refused")
    )
    with _patch_redis(client):
        await set_cached(_INTEGRATION_ID, {"temp": "15 °C"})


@pytest.mark.asyncio
async def test_del_cached_fails_open():
    """del_cached runs inside connect()/sync(); a Redis outage must not abort
    an otherwise-successful reconnect."""
    client = AsyncMock()
    client.delete = AsyncMock(
        side_effect=redis.exceptions.ConnectionError("Connection refused")
    )
    with _patch_redis(client):
        await del_cached(_INTEGRATION_ID)


@pytest.mark.asyncio
async def test_get_cached_fails_open_when_the_client_itself_is_unavailable():
    """get_redis() is inside the try, so a connection that fails at acquire
    time degrades the same way as one that fails at read time."""
    with patch(
        "backend.src.services.weather.cache.get_redis",
        AsyncMock(side_effect=redis.exceptions.ConnectionError("no pool")),
    ):
        assert await get_cached(_INTEGRATION_ID) is None


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_del_cached_deletes_the_namespaced_key():
    client = AsyncMock()
    with _patch_redis(client):
        await del_cached(_INTEGRATION_ID)

    client.delete.assert_awaited_once_with(cache_key(_INTEGRATION_ID))
