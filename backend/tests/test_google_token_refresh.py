"""Regression test: a failed Google token refresh must not surface as a 500.

Production incident 2026-10-05 — a revoked refresh token made Google's token
endpoint return 400 invalid_grant. The httpx.HTTPStatusError escaped
_refresh(), so /dashboard/events and /dashboard/briefing returned 500
instead of falling back to cached data.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.services import google_token
from src.services.google_token import TokenUnavailableError


def _mock_client(post: AsyncMock) -> MagicMock:
    client = AsyncMock()
    client.post = post
    client_cls = MagicMock()
    client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
    client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return client_cls


def _token_row() -> MagicMock:
    row = MagicMock()
    row.encrypted_refresh_token = "enc-refresh"
    return row


@pytest.mark.asyncio
async def test_refresh_invalid_grant_raises_token_unavailable():
    request = httpx.Request("POST", google_token._GOOGLE_TOKEN_URL)
    response = httpx.Response(400, json={"error": "invalid_grant"}, request=request)
    client_cls = _mock_client(AsyncMock(return_value=response))
    db = AsyncMock()

    with (
        patch.object(google_token, "decrypt", return_value="refresh"),
        patch.object(google_token.httpx, "AsyncClient", client_cls),
    ):
        with pytest.raises(TokenUnavailableError):
            await google_token._refresh(_token_row(), db)

    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_network_error_raises_token_unavailable():
    client_cls = _mock_client(AsyncMock(side_effect=httpx.ConnectTimeout("timeout")))

    with (
        patch.object(google_token, "decrypt", return_value="refresh"),
        patch.object(google_token.httpx, "AsyncClient", client_cls),
    ):
        with pytest.raises(TokenUnavailableError):
            await google_token._refresh(_token_row(), AsyncMock())


@pytest.mark.asyncio
async def test_refresh_success_stores_new_access_token():
    request = httpx.Request("POST", google_token._GOOGLE_TOKEN_URL)
    response = httpx.Response(
        200, json={"access_token": "new-access", "expires_in": 3600}, request=request
    )
    client_cls = _mock_client(AsyncMock(return_value=response))
    row = _token_row()
    db = AsyncMock()

    with (
        patch.object(google_token, "decrypt", return_value="refresh"),
        patch.object(google_token, "encrypt", return_value="enc-new-access"),
        patch.object(google_token.httpx, "AsyncClient", client_cls),
    ):
        result = await google_token._refresh(row, db)

    assert result == "new-access"
    assert row.encrypted_access_token == "enc-new-access"
    db.commit.assert_awaited_once()
