"""Tests for Google token lookup and refresh (src/services/google_token.py).

Regression guard for the 2026-10-05 incident: a revoked refresh token made
Google's token endpoint return 400 invalid_grant. The httpx.HTTPStatusError
escaped _refresh(), so /dashboard/events and /dashboard/briefing returned 500
instead of falling back to cached data.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.auth.crypto import TokenDecryptError
from src.services import google_token
from src.services.google_token import TokenUnavailableError

_REQUEST = httpx.Request("POST", google_token._GOOGLE_TOKEN_URL)


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
    row.encrypted_access_token = "enc-original"
    row.token_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return row


def _respond(response: httpx.Response):
    return patch.object(
        google_token.httpx,
        "AsyncClient",
        _mock_client(AsyncMock(return_value=response)),
    )


class TestRefresh:
    @pytest.mark.asyncio
    async def test_invalid_grant_raises_token_unavailable_and_changes_nothing(self):
        row, db = _token_row(), AsyncMock()
        response = httpx.Response(
            400, json={"error": "invalid_grant"}, request=_REQUEST
        )
        with patch.object(google_token, "decrypt", return_value="refresh"):
            with _respond(response):
                with pytest.raises(TokenUnavailableError):
                    await google_token._refresh(row, db)
        assert row.encrypted_access_token == "enc-original"
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_original_error_is_logged(self, caplog):
        response = httpx.Response(
            400, json={"error": "invalid_grant"}, request=_REQUEST
        )
        with patch.object(google_token, "decrypt", return_value="refresh"):
            with _respond(response):
                with caplog.at_level(logging.WARNING, logger=google_token.__name__):
                    with pytest.raises(TokenUnavailableError):
                        await google_token._refresh(_token_row(), AsyncMock())
        assert "Google token refresh failed" in caplog.text
        assert "400" in caplog.text
        assert "refresh" not in caplog.text.replace("Google token refresh failed", "")

    @pytest.mark.asyncio
    async def test_network_error_raises_token_unavailable(self):
        client_cls = _mock_client(
            AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
        )
        with patch.object(google_token, "decrypt", return_value="refresh"):
            with patch.object(google_token.httpx, "AsyncClient", client_cls):
                with pytest.raises(TokenUnavailableError):
                    await google_token._refresh(_token_row(), AsyncMock())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [500, 502, 503])
    async def test_google_server_error_raises_token_unavailable(self, status):
        response = httpx.Response(status, request=_REQUEST)
        with patch.object(google_token, "decrypt", return_value="refresh"):
            with _respond(response):
                with pytest.raises(TokenUnavailableError):
                    await google_token._refresh(_token_row(), AsyncMock())

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(200, content=b"not json", request=_REQUEST),
            httpx.Response(200, json={"expires_in": 3600}, request=_REQUEST),
            httpx.Response(200, json=["a", "list"], request=_REQUEST),
            httpx.Response(
                200, json={"access_token": "t", "expires_in": "abc"}, request=_REQUEST
            ),
        ],
        ids=["non-json", "missing-access-token", "list-body", "bad-expires-in"],
    )
    async def test_a_200_with_an_unusable_body_raises_token_unavailable(self, response):
        row, db = _token_row(), AsyncMock()
        with patch.object(google_token, "decrypt", return_value="refresh"):
            with _respond(response):
                with pytest.raises(TokenUnavailableError):
                    await google_token._refresh(row, db)
        assert row.encrypted_access_token == "enc-original"
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_stores_the_new_access_token_and_expiry(self):
        response = httpx.Response(
            200,
            json={"access_token": "new-access", "expires_in": 3600},
            request=_REQUEST,
        )
        row, db = _token_row(), AsyncMock()
        with patch.object(google_token, "decrypt", return_value="refresh"):
            with patch.object(google_token, "encrypt", return_value="enc-new"):
                with _respond(response):
                    result = await google_token._refresh(row, db)
        assert result == "new-access"
        assert row.encrypted_access_token == "enc-new"
        remaining = row.token_expires_at - datetime.now(timezone.utc)
        assert timedelta(minutes=59) < remaining <= timedelta(minutes=60)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_refresh_token_stored_raises_token_unavailable(self):
        row = _token_row()
        row.encrypted_refresh_token = None
        with pytest.raises(TokenUnavailableError):
            await google_token._refresh(row, AsyncMock())

    @pytest.mark.asyncio
    async def test_undecryptable_refresh_token_raises_token_unavailable(self):
        with patch.object(
            google_token, "decrypt", side_effect=TokenDecryptError("bad")
        ):
            with pytest.raises(TokenUnavailableError):
                await google_token._refresh(_token_row(), AsyncMock())


class TestIsExpiring:
    def test_no_expiry_means_not_expiring(self):
        assert google_token._is_expiring(None) is False

    def test_far_future_is_not_expiring(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert google_token._is_expiring(future) is False

    def test_past_is_expiring(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert google_token._is_expiring(past) is True

    def test_inside_the_buffer_is_expiring(self):
        soon = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert google_token._is_expiring(soon) is True

    def test_just_outside_the_buffer_is_not_expiring(self):
        later = datetime.now(timezone.utc) + timedelta(seconds=120)
        assert google_token._is_expiring(later) is False

    def test_a_naive_timestamp_is_treated_as_utc(self):
        naive_soon = (datetime.now(timezone.utc) + timedelta(seconds=30)).replace(
            tzinfo=None
        )
        naive_later = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(
            tzinfo=None
        )
        assert google_token._is_expiring(naive_soon) is True
        assert google_token._is_expiring(naive_later) is False


class TestGetValidGoogleToken:
    @staticmethod
    def _db(*rows):
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=list(rows))
        return db

    @pytest.mark.asyncio
    async def test_no_linked_google_account(self):
        with pytest.raises(TokenUnavailableError, match="No Google account"):
            await google_token.get_valid_google_token(uuid.uuid4(), self._db(None))

    @pytest.mark.asyncio
    async def test_no_token_row(self):
        db = self._db(MagicMock(id=uuid.uuid4()), None)
        with pytest.raises(TokenUnavailableError, match="No token row"):
            await google_token.get_valid_google_token(uuid.uuid4(), db)

    @pytest.mark.asyncio
    async def test_undecryptable_access_token(self):
        db = self._db(MagicMock(id=uuid.uuid4()), _token_row())
        with patch.object(
            google_token, "decrypt", side_effect=TokenDecryptError("bad")
        ):
            with pytest.raises(TokenUnavailableError, match="decryption failed"):
                await google_token.get_valid_google_token(uuid.uuid4(), db)

    @pytest.mark.asyncio
    async def test_a_fresh_token_is_returned_without_refreshing(self):
        row = _token_row()
        row.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db = self._db(MagicMock(id=uuid.uuid4()), row)
        refresh = AsyncMock()
        with patch.object(google_token, "decrypt", return_value="live-token"):
            with patch.object(google_token, "_refresh", refresh):
                token = await google_token.get_valid_google_token(uuid.uuid4(), db)
        assert token == "live-token"
        refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_expiring_token_is_refreshed(self):
        row = _token_row()
        row.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=10)
        db = self._db(MagicMock(id=uuid.uuid4()), row)
        refresh = AsyncMock(return_value="refreshed-token")
        with patch.object(google_token, "decrypt", return_value="stale-token"):
            with patch.object(google_token, "_refresh", refresh):
                token = await google_token.get_valid_google_token(uuid.uuid4(), db)
        assert token == "refreshed-token"
        refresh.assert_awaited_once_with(row, db)
