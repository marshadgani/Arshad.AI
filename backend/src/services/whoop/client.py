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


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def get(
    path: str, access_token: str, params: dict[str, Any] | None = None
) -> Any:
    """Single authenticated GET against the Whoop API, raising for status."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
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

    One client for all three so the dashboard costs a single connection
    setup rather than three sequential round trips.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        recovery, sleep, strain = await gather_get(
            client,
            auth_headers(access_token),
            [RECOVERY_PATH, SLEEP_PATH, CYCLE_PATH],
            [{"limit": 1}, {"limit": 1}, {"limit": 1}],
        )
    return recovery, sleep, strain
