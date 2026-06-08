"""Unit tests for refresh_google_token in backend/src/tools/token_service.py.

Tests all critical paths:
  1. Success — returns plaintext access token, persists encrypted token
  2. Google 400 invalid_grant — raises ProviderReauthRequired
  3. Google 401 invalid_grant — raises ProviderReauthRequired
  4. token_row is None — raises ProviderReauthRequired
  5. token_row.encrypted_refresh_token is None — raises ProviderReauthRequired
  6. Google 500 — raises httpx.HTTPStatusError (not ProviderReauthRequired)
  7. Token rotation — new refresh_token from Google is persisted
  8. None expires_in — token_expires_at set to None
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_row(has_refresh: bool = True) -> MagicMock:
    row = MagicMock()
    row.encrypted_refresh_token = b"enc_refresh" if has_refresh else None
    row.encrypted_access_token = b"enc_old_access"
    row.token_expires_at = None
    return row


def _make_db(token_row) -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=token_row)
    db.commit = AsyncMock()
    return db


def _make_response(status_code: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=body or {})
    if status_code >= 400:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status_code}",
                request=MagicMock(),
                response=resp,
            )
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


ACCOUNT_ID = uuid.uuid4()

ENV_PATCH = {
    "GOOGLE_OAUTH_CLIENT_ID": "test-client-id",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRefreshGoogleTokenSuccess:
    async def test_returns_plaintext_access_token(self):
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(
            200, {"access_token": "new_access_123", "expires_in": 3600}
        )

        with (
            patch("src.tools.token_service.decrypt", return_value="plaintext_refresh"),
            patch("src.tools.token_service.encrypt", return_value=b"enc_new"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.token_service import refresh_google_token

            result = await refresh_google_token(db, ACCOUNT_ID)

        assert result == "new_access_123"

    async def test_persists_encrypted_access_token(self):
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(200, {"access_token": "new_tok", "expires_in": 3600})

        with (
            patch("src.tools.token_service.decrypt", return_value="plaintext_refresh"),
            patch("src.tools.token_service.encrypt", return_value=b"enc_new"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.token_service import refresh_google_token

            await refresh_google_token(db, ACCOUNT_ID)

        assert token_row.encrypted_access_token == b"enc_new"
        db.commit.assert_awaited_once()

    async def test_sets_expiry_when_expires_in_present(self):
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(200, {"access_token": "t", "expires_in": 3600})

        with (
            patch("src.tools.token_service.decrypt", return_value="r"),
            patch("src.tools.token_service.encrypt", return_value=b"e"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.token_service import refresh_google_token

            await refresh_google_token(db, ACCOUNT_ID)

        assert token_row.token_expires_at is not None
        assert token_row.token_expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
class TestRefreshGoogleTokenInvalidGrant:
    async def test_google_400_raises_provider_reauth(self):
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(400)

        with (
            patch("src.tools.token_service.decrypt", return_value="r"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.base import ProviderReauthRequired
            from src.tools.token_service import refresh_google_token

            with pytest.raises(ProviderReauthRequired) as exc_info:
                await refresh_google_token(db, ACCOUNT_ID)

        assert exc_info.value.args[0] == "google"

    async def test_google_401_raises_provider_reauth(self):
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(401)

        with (
            patch("src.tools.token_service.decrypt", return_value="r"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.base import ProviderReauthRequired
            from src.tools.token_service import refresh_google_token

            with pytest.raises(ProviderReauthRequired):
                await refresh_google_token(db, ACCOUNT_ID)


@pytest.mark.asyncio
class TestRefreshGoogleTokenMissingRow:
    async def test_no_token_row_raises_provider_reauth(self):
        db = _make_db(token_row=None)

        from src.tools.base import ProviderReauthRequired
        from src.tools.token_service import refresh_google_token

        with pytest.raises(ProviderReauthRequired) as exc_info:
            await refresh_google_token(db, ACCOUNT_ID)

        assert exc_info.value.args[0] == "google"

    async def test_no_refresh_token_raises_provider_reauth(self):
        token_row = _make_token_row(has_refresh=False)
        db = _make_db(token_row)

        from src.tools.base import ProviderReauthRequired
        from src.tools.token_service import refresh_google_token

        with pytest.raises(ProviderReauthRequired):
            await refresh_google_token(db, ACCOUNT_ID)


@pytest.mark.asyncio
class TestRefreshGoogleTokenServerError:
    async def test_google_500_raises_http_status_error(self):
        """Non-400/401 errors propagate as httpx.HTTPStatusError, not ProviderReauthRequired."""
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(500)

        with (
            patch("src.tools.token_service.decrypt", return_value="r"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.token_service import refresh_google_token

            with pytest.raises(httpx.HTTPStatusError):
                await refresh_google_token(db, ACCOUNT_ID)


@pytest.mark.asyncio
class TestRefreshGoogleTokenRotation:
    async def test_new_refresh_token_persisted(self):
        """When Google returns a new refresh_token, it must be stored."""
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(
            200,
            {
                "access_token": "new_access",
                "refresh_token": "rotated_refresh",
                "expires_in": 3600,
            },
        )

        encrypted_values = []

        def _fake_encrypt(value: str) -> bytes:
            encrypted_values.append(value)
            return f"enc_{value}".encode()

        with (
            patch("src.tools.token_service.decrypt", return_value="old_refresh"),
            patch("src.tools.token_service.encrypt", side_effect=_fake_encrypt),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.token_service import refresh_google_token

            await refresh_google_token(db, ACCOUNT_ID)

        assert "rotated_refresh" in encrypted_values
        assert token_row.encrypted_refresh_token == b"enc_rotated_refresh"

    async def test_no_new_refresh_token_not_overwritten(self):
        """When Google does not return a new refresh_token, the existing one is kept."""
        token_row = _make_token_row()
        original_refresh = token_row.encrypted_refresh_token
        db = _make_db(token_row)
        resp = _make_response(200, {"access_token": "new_access", "expires_in": 3600})

        with (
            patch("src.tools.token_service.decrypt", return_value="old_refresh"),
            patch("src.tools.token_service.encrypt", return_value=b"enc_new_access"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.token_service import refresh_google_token

            await refresh_google_token(db, ACCOUNT_ID)

        assert token_row.encrypted_refresh_token == original_refresh


@pytest.mark.asyncio
class TestRefreshGoogleTokenNoneExpiry:
    async def test_none_expires_in_sets_null_expiry(self):
        """When expires_in is absent, token_expires_at must be set to None."""
        token_row = _make_token_row()
        db = _make_db(token_row)
        resp = _make_response(200, {"access_token": "tok"})  # no expires_in

        with (
            patch("src.tools.token_service.decrypt", return_value="r"),
            patch("src.tools.token_service.encrypt", return_value=b"e"),
            patch(
                "src.tools.token_service.required_env",
                side_effect=lambda k: ENV_PATCH[k],
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from src.tools.token_service import refresh_google_token

            await refresh_google_token(db, ACCOUNT_ID)

        assert token_row.token_expires_at is None
