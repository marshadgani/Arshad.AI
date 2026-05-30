"""Gmail HTTP client.

Same refresh-on-401 contract as the Calendar client. Gmail's API base
is gmail/v1; the user's mailbox is always referenced as ``users/me``
to avoid hard-coding email addresses (the access token already binds
to the right user).

Endpoint reference: https://developers.google.com/gmail/api/v1/reference
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import ProviderReauthRequired, ToolError
from ..token_service import get_access_token, refresh_google_token

_BASE = "https://gmail.googleapis.com/gmail/v1"
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
    access_token, account = await get_access_token(db, user, "google")

    async with httpx.AsyncClient(timeout=_TIMEOUT, base_url=_BASE) as client:
        resp = await _send(client, access_token, method, path, params, json)

        if resp.status_code == 401:
            access_token = await refresh_google_token(db, account.id)
            resp = await _send(client, access_token, method, path, params, json)
            if resp.status_code == 401:
                raise ProviderReauthRequired("google")

    return _resolve(resp)


async def _send(
    client: httpx.AsyncClient,
    access_token: str,
    method: str,
    path: str,
    params: dict[str, Any] | None,
    json: dict[str, Any] | None,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    return await client.request(method, path, params=params, json=json, headers=headers)


def _resolve(resp: httpx.Response) -> Any:
    if resp.status_code >= 500:
        raise ToolError(
            "provider_http_error",
            f"Gmail returned {resp.status_code}: {resp.text[:200]}",
        )
    if resp.status_code >= 400:
        raise ToolError(
            "provider_request_failed",
            f"Gmail rejected request ({resp.status_code}): {resp.text[:200]}",
        )
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()
