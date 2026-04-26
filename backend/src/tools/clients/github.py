"""GitHub HTTP client.

GitHub OAuth Apps don't issue refresh tokens (Phase C decision). On 401,
we raise ProviderReauthRequired('github') directly — no retry — so the
frontend can show "click to reconnect GitHub". No silent retry path.

Endpoint reference: https://docs.github.com/en/rest
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import ProviderReauthRequired, ToolError
from ..token_service import get_access_token

_BASE = "https://api.github.com"
_TIMEOUT = 15.0


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
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, base_url=_BASE, headers=headers
    ) as client:
        resp = await client.request(method, path, params=params, json=json)

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
