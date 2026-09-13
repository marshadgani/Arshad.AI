"""GitHub HTTP client.

GitHub OAuth Apps don't issue refresh tokens (Phase C decision). On 401,
we raise ProviderReauthRequired('github') directly — no retry — so the
frontend can show "click to reconnect GitHub". No silent retry path.

Endpoint reference: https://docs.github.com/en/rest
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import ProviderReauthRequired, ToolError
from ..token_service import get_access_token

_BASE = "https://api.github.com"
_TIMEOUT = 15.0

# Every call used to open `async with httpx.AsyncClient(...)`, pay a fresh
# TCP+TLS handshake to api.github.com, and tear the connection back down.
# FEAT-139's ingestion run calls this twice per linked repo (issues + PRs)
# in immediate succession, so that handshake cost was being paid on every
# single call instead of once per run. A shared, lazily-built client with
# keep-alive pooling (same lazy-singleton shape as middleware/cache.py's
# get_redis and services/whoop/client.py's _get_client) lets consecutive
# GitHub calls reuse a warm connection. Auth is per-user, so headers are
# passed per-request rather than baked into the shared client.
_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            _client = httpx.AsyncClient(
                timeout=_TIMEOUT,
                base_url=_BASE,
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


async def request(
    *,
    db: AsyncSession,
    user: User,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> Any:
    access_token, _ = await get_access_token(db, user, "github")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    client = await _get_client()
    resp = await client.request(method, path, params=params, json=json, headers=headers)

    if resp.status_code == 401:
        raise ProviderReauthRequired("github")
    if resp.status_code == 403:
        # Either rate limited or scope-denied. Surface verbatim — Claude can
        # tell the user "you need additional scopes" or "wait for rate limit".
        raise ToolError(
            "github_forbidden",
            f"GitHub forbade the request: {resp.text[:200]}",
        )
    if resp.status_code >= 500:
        raise ToolError(
            "provider_http_error",
            f"GitHub returned {resp.status_code}: {resp.text[:200]}",
        )
    if resp.status_code >= 400:
        raise ToolError(
            "provider_request_failed",
            f"GitHub rejected request ({resp.status_code}): {resp.text[:200]}",
        )
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()
