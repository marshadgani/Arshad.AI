"""Tests for the shared pooled Whoop httpx client — singleton lifecycle and
concurrent-fetch cleanup.

This module was flagged as the lowest-coverage file remaining in the
Apple Health / Whoop / Shopify diff after the rest of the gate's
test-writer gaps were closed. It's also where the gate's debugger
finding lived (main.py called a `close_whoop_client` that was never
imported, meaning `aclose_client` was never actually exercised by any
running process, let alone a test) — so the singleton and its close
path get direct coverage here rather than staying implicit.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.services.whoop import client as whoop_client


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Every test starts and ends with a clean module-level `_client`, so
    tests don't leak a real/mock AsyncClient into the next test's
    `_get_client()` call. Each test's own event loop is torn down by
    pytest-asyncio when the test ends, which closes any real httpx
    transport this fixture doesn't explicitly await-close."""
    whoop_client._client = None
    yield
    whoop_client._client = None


class TestGetClientSingleton:
    @pytest.mark.asyncio
    async def test_first_call_constructs_a_pooled_client(self):
        client = await whoop_client._get_client()
        assert isinstance(client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_second_call_reuses_the_same_instance(self):
        """The whole point of the singleton is connection reuse — a second
        call that built a new client would defeat the keep-alive pooling
        the module docstring promises."""
        first = await whoop_client._get_client()
        second = await whoop_client._get_client()
        assert first is second

    @pytest.mark.asyncio
    async def test_concurrent_first_calls_still_yield_one_client(self):
        """Two callers racing on a cold `_client` must not each construct
        their own AsyncClient — the `_client_lock` double-checked-locking
        pattern exists specifically to prevent this."""
        results = await asyncio.gather(
            whoop_client._get_client(), whoop_client._get_client()
        )
        assert results[0] is results[1]


class TestAcloseClient:
    @pytest.mark.asyncio
    async def test_closes_the_underlying_client(self):
        client = await whoop_client._get_client()
        client.aclose = AsyncMock()

        await whoop_client.aclose_client()

        client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resets_singleton_so_a_later_call_builds_a_fresh_client(self):
        """This is the exact behaviour main.py's shutdown hook depends on:
        without the reset, a process that somehow reused the module after
        shutdown would hand out a client whose transport is already closed."""
        first = await whoop_client._get_client()
        first.aclose = AsyncMock()

        await whoop_client.aclose_client()
        second = await whoop_client._get_client()

        assert second is not first

    @pytest.mark.asyncio
    async def test_is_a_no_op_when_never_initialised(self):
        """Called on an app that shut down before any Whoop request ever
        ran — must not raise on a None client."""
        await whoop_client.aclose_client()  # no exception


class TestGatherGet:
    @pytest.mark.asyncio
    async def test_returns_results_in_path_order(self):
        client = MagicMock()

        async def fake_get(url, headers, params):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={"path": url})
            return resp

        client.get = AsyncMock(side_effect=fake_get)

        results = await whoop_client.gather_get(
            client, {}, ["/a", "/b"], [{}, {}]
        )

        assert results[0]["path"].endswith("/a")
        assert results[1]["path"].endswith("/b")

    @pytest.mark.asyncio
    async def test_cancels_stragglers_and_reraises_on_partial_failure(self):
        """Regression guard for the module's own documented failure mode:
        without cancel-and-drain, a slow sibling task keeps running after
        this function raises and the caller's client may already be
        closed by then — surfacing as an unretrieved-exception warning
        instead of a clean propagation."""
        client = MagicMock()
        started = asyncio.Event()
        released = asyncio.Event()

        async def slow_ok(url, headers, params):
            started.set()
            await released.wait()
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={})
            return resp

        async def fails(url, headers, params):
            await started.wait()
            raise httpx.HTTPStatusError(
                "boom", request=MagicMock(), response=MagicMock(status_code=500)
            )

        async def route(url, headers, params):
            fn = fails if "/fail" in url else slow_ok
            return await fn(url, headers, params)

        client.get = AsyncMock(side_effect=route)

        with pytest.raises(httpx.HTTPStatusError):
            await whoop_client.gather_get(
                client, {}, ["/slow", "/fail"], [{}, {}]
            )

        released.set()  # let the straggler finish so it doesn't leak into the next test


class TestFetchDashboardBodies:
    @pytest.mark.asyncio
    async def test_fetches_recovery_sleep_cycle_concurrently(self, monkeypatch):
        client = MagicMock()

        async def fake_get(url, headers, params):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if whoop_client.RECOVERY_PATH in url:
                resp.json = MagicMock(return_value={"kind": "recovery"})
            elif whoop_client.SLEEP_PATH in url:
                resp.json = MagicMock(return_value={"kind": "sleep"})
            else:
                resp.json = MagicMock(return_value={"kind": "cycle"})
            return resp

        client.get = AsyncMock(side_effect=fake_get)
        monkeypatch.setattr(whoop_client, "_get_client", AsyncMock(return_value=client))

        recovery, sleep, strain = await whoop_client.fetch_dashboard_bodies("tok")

        assert recovery["kind"] == "recovery"
        assert sleep["kind"] == "sleep"
        assert strain["kind"] == "cycle"


def test_auth_headers_uses_bearer_scheme():
    assert whoop_client.auth_headers("abc123") == {"Authorization": "Bearer abc123"}
