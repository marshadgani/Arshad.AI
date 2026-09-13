"""Tests for integrations.base.needs_reauth, _oauth_base.record_sync_failure,
and _oauth_base.make_oauth_sync_via_api error-classification behaviour.

All tests use mocked httpx transports and AsyncMock integration rows — no DB
or live HTTP connections. pytest-asyncio is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.integrations.base import (
    REAUTH_CODES,
    IntegrationError,
    needs_reauth,
)
from src.integrations.personal._oauth_base import (
    make_oauth_sync_via_api,
    record_sync_failure,
)

# ── needs_reauth ───────────────────────────────────────────────────────────────


class TestNeedsReauth:
    @pytest.mark.parametrize("code", sorted(REAUTH_CODES))
    def test_integration_error_reauth_codes_return_true(self, code):
        exc = IntegrationError(code, "msg")
        assert needs_reauth(exc) is True

    def test_integration_error_non_reauth_code_returns_false(self):
        exc = IntegrationError("sync_failed", "msg")
        assert needs_reauth(exc) is False

    def test_http_401_returns_true(self):
        response = MagicMock(status_code=401)
        exc = httpx.HTTPStatusError("401", request=MagicMock(), response=response)
        assert needs_reauth(exc) is True

    def test_http_403_returns_true(self):
        response = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=response)
        assert needs_reauth(exc) is True

    def test_http_500_returns_false(self):
        response = MagicMock(status_code=500)
        exc = httpx.HTTPStatusError("500", request=MagicMock(), response=response)
        assert needs_reauth(exc) is False

    def test_request_error_no_response_attr_safe(self):
        # httpx.RequestError (ConnectTimeout, ReadTimeout, etc.) has no
        # .response attribute — needs_reauth must not raise AttributeError.
        exc = httpx.ConnectTimeout("timed out", request=MagicMock())
        assert needs_reauth(exc) is False

    def test_generic_exception_returns_false(self):
        assert needs_reauth(ValueError("boom")) is False

    def test_extra_codes_parameter_respected(self):
        exc = IntegrationError("custom_code", "msg")
        assert needs_reauth(exc, extra_codes=frozenset({"custom_code"})) is True


# ── record_sync_failure ────────────────────────────────────────────────────────


def _make_integration(status="connected"):
    integration = MagicMock()
    integration.status = status
    integration.last_error = None
    integration.slug = "upstox"
    return integration


@pytest.mark.asyncio
class TestRecordSyncFailure:
    async def test_401_sets_expired(self):
        integration = _make_integration()
        db = AsyncMock()
        response = MagicMock(status_code=401)
        exc = httpx.HTTPStatusError("401", request=MagicMock(), response=response)

        result = await record_sync_failure(integration, exc, db, slug="upstox")

        assert integration.status == "expired"
        assert result is True
        db.commit.assert_awaited_once()

    async def test_403_sets_expired(self):
        integration = _make_integration()
        db = AsyncMock()
        response = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=response)

        await record_sync_failure(integration, exc, db, slug="zerodha_kite")

        assert integration.status == "expired"

    async def test_no_refresh_token_sets_expired(self):
        integration = _make_integration()
        db = AsyncMock()
        exc = IntegrationError("no_refresh_token", "token expired")

        result = await record_sync_failure(integration, exc, db, slug="zerodha_kite")

        assert integration.status == "expired"
        assert result is True

    async def test_500_sets_error(self):
        integration = _make_integration()
        db = AsyncMock()
        response = MagicMock(status_code=500)
        exc = httpx.HTTPStatusError("500", request=MagicMock(), response=response)

        result = await record_sync_failure(integration, exc, db, slug="upstox")

        assert integration.status == "error"
        assert result is False

    async def test_timeout_sets_error(self):
        integration = _make_integration()
        db = AsyncMock()
        exc = httpx.ReadTimeout("timed out", request=MagicMock())

        await record_sync_failure(integration, exc, db, slug="upstox")

        assert integration.status == "error"

    async def test_last_error_written_to_db(self):
        integration = _make_integration()
        db = AsyncMock()
        exc = ValueError("something broke")

        await record_sync_failure(integration, exc, db, slug="upstox")

        assert integration.last_error is not None
        assert "ValueError" in integration.last_error

    async def test_last_error_truncated_to_500_chars(self):
        integration = _make_integration()
        db = AsyncMock()
        exc = ValueError("x" * 1000)

        await record_sync_failure(integration, exc, db, slug="upstox")

        assert len(integration.last_error) <= 500

    async def test_never_raises(self):
        """A DB commit failure must not mask the original sync error."""
        integration = _make_integration()
        db = AsyncMock()
        db.commit.side_effect = RuntimeError("DB gone")
        exc = ValueError("original error")

        # Should not raise despite the DB failure
        await record_sync_failure(integration, exc, db, slug="upstox")


# ── make_oauth_sync_via_api ────────────────────────────────────────────────────


class _FakeProvider:
    """Minimal stand-in for an OAuthIntegrationProvider subclass."""

    slug = "test_provider"
    display_name = "Test Provider"

    async def get_access_token(
        self, *, integration, db
    ) -> str:  # default: return a token
        return "tok_abc"


@pytest.mark.asyncio
class TestMakeOAuthSyncViaApi:
    def _make_integration(self):
        integration = MagicMock()
        integration.status = "connected"
        integration.last_error = None
        integration.last_synced_at = None
        integration.config = {}
        integration.slug = "test_provider"
        return integration

    async def test_success_sets_connected_and_clears_error(self):
        provider = _FakeProvider()
        integration = self._make_integration()
        db = AsyncMock()

        body = {"data": [{"symbol": "OK", "qty": 1}]}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.json.return_value = body
            mock_response.raise_for_status.return_value = None
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            sync_fn = make_oauth_sync_via_api(
                sync_url="https://api.example.com/data",
                parse_sync=lambda b: {"count": len(b.get("data", []))},
            )
            result = await sync_fn(provider, integration=integration, db=db)

        assert integration.status == "connected"
        assert integration.last_error is None
        assert result.rows_written == 0

    async def test_401_from_api_sets_expired(self):
        provider = _FakeProvider()
        integration = self._make_integration()
        db = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            response = MagicMock(status_code=401)
            exc = httpx.HTTPStatusError("401", request=MagicMock(), response=response)
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.side_effect = exc
            mock_client_cls.return_value = mock_client

            sync_fn = make_oauth_sync_via_api(
                sync_url="https://api.example.com/data",
                parse_sync=None,
            )
            with pytest.raises(IntegrationError):
                await sync_fn(provider, integration=integration, db=db)

        assert integration.status == "expired"

    async def test_500_from_api_sets_error(self):
        provider = _FakeProvider()
        integration = self._make_integration()
        db = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            response = MagicMock(status_code=500)
            exc = httpx.HTTPStatusError("500", request=MagicMock(), response=response)
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.side_effect = exc
            mock_client_cls.return_value = mock_client

            sync_fn = make_oauth_sync_via_api(
                sync_url="https://api.example.com/data",
                parse_sync=None,
            )
            with pytest.raises(IntegrationError):
                await sync_fn(provider, integration=integration, db=db)

        assert integration.status == "error"

    async def test_preflight_token_failure_sets_expired(self):
        """A no_refresh_token error from get_access_token must mark the
        integration as 'expired', not leave it stuck on 'connected'.
        This was the primary defect FEAT-137 fixes.
        """

        class _NoTokenProvider(_FakeProvider):
            async def get_access_token(self, *, integration, db) -> str:
                raise IntegrationError("no_refresh_token", "token expired")

        provider = _NoTokenProvider()
        integration = self._make_integration()
        db = AsyncMock()

        sync_fn = make_oauth_sync_via_api(
            sync_url="https://api.example.com/data",
            parse_sync=None,
        )
        with pytest.raises(IntegrationError):
            await sync_fn(provider, integration=integration, db=db)

        assert integration.status == "expired"
