"""Upstream transport for the Whoop Developer API.

Knows how to issue authenticated GETs and fan several out concurrently.
Deliberately knows nothing about FastAPI, the database, or the Integration
model — a change to Whoop's HTTP surface is contained entirely here, and
these functions can be exercised against a stub client without a request
context or a DB session.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

BASE_URL = "https://api.prod.whoop.com/developer/v1"

REQUEST_TIMEOUT_SECONDS = 15.0

# Endpoint paths, named so callers read as intent rather than URL strings.
RECOVERY_PATH = "/recovery"
SLEEP_PATH = "/sleep"
CYCLE_PATH = "/cycle"
WORKOUT_PATH = "/workout"

# Every call used to open `async with httpx.AsyncClient(...)`, pay a fresh
# TCP+TLS handshake to api.prod.whoop.com, and tear the connection back
# down — on /hrv-trend and /workouts that handshake is the entire request's
# transport cost, since each only issues one upstream GET. A shared,
# lazily-built client with keep-alive pooling (same lazy-singleton shape as
# middleware/cache.py's get_redis) lets consecutive Whoop calls reuse a warm
# connection instead of re-negotiating TLS every time.
_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            _client = httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
    return _client


async def aclose_client() -> None:
    """Close the shared client. Called from the app's shutdown hook so the
    pooled connection doesn't outlive the process' event loop."""
    global _client
    async with _client_lock:
        if _client is not None:
            await _client.aclose()
            _client = None


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def get(
    path: str, access_token: str, params: dict[str, Any] | None = None
) -> Any:
    """Single authenticated GET against the Whoop API, raising for status."""
    client = await _get_client()
    resp = await client.get(
        f"{BASE_URL}{path}",
        headers=auth_headers(access_token),
        params=params or {},
    )
    resp.raise_for_status()
    return resp.json()


async def gather_get(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    paths: list[str],
    params_list: list[dict[str, Any]],
) -> list[Any]:
    """Fan out N GETs on the shared client and await them all.

    On a partial failure, `asyncio.gather` (without `return_exceptions=True`)
    re-raises the first exception immediately but leaves the other tasks
    running in the background — including after the caller's
    `async with httpx.AsyncClient()` block has already exited and closed the
    client. A still-running task then either issues a request through a
    closed client or has its exception logged as "never retrieved" by
    asyncio, neither of which the caller ever sees. Cancel the stragglers
    and drain their outcomes before propagating, so the client is only ever
    used while open and no background task escapes this function.
    """

    async def fetch(path: str, params: dict[str, Any]) -> Any:
        resp = await client.get(f"{BASE_URL}{path}", headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    tasks = [asyncio.ensure_future(fetch(p, q)) for p, q in zip(paths, params_list)]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def fetch_dashboard_bodies(access_token: str) -> tuple[Any, Any, Any]:
    """Concurrently fetch the latest recovery, sleep and cycle records.

    Uses the shared pooled client so the three concurrent GETs fan out over
    already-warm connections instead of paying three TLS handshakes (or,
    previously, a fresh one per dashboard poll) against the same host.
    """
    client = await _get_client()
    recovery, sleep, strain = await gather_get(
        client,
        auth_headers(access_token),
        [RECOVERY_PATH, SLEEP_PATH, CYCLE_PATH],
        [{"limit": 1}, {"limit": 1}, {"limit": 1}],
    )
    return recovery, sleep, strain
