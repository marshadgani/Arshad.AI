"""Provider-level sync tests for Upstox and Zerodha Kite.

Verifies:
  - All four holding fields (symbol, qty, ltp, pnl) are populated on success
  - MAX_STORED_HOLDINGS bound is honoured (only first 10 rows stored)
  - 401 from broker API → integration.status == 'expired'
  - 500 from broker API → integration.status == 'error'
  - Zerodha-specific defect: no_refresh_token from get_access_token →
    status='expired' (not stuck at 'connected')
  - WP-2 regression guard: BrokerHoldings.error never contains raw exception
    text or internal URLs
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal._shared import MAX_STORED_HOLDINGS
from src.integrations.personal.upstox import UpstoxIntegration
from src.integrations.personal.zerodha_kite import ZerodhaKiteIntegration
from src.services.finance.holdings import _safe_error_message


def _make_integration(slug="upstox", status="connected"):
    integration = MagicMock()
    integration.status = status
    integration.last_error = None
    integration.last_synced_at = None
    integration.config = {}
    integration.slug = slug
    return integration


def _upstox_holdings_body(n: int = 3) -> dict:
    return {
        "data": [
            {
                "trading_symbol": f"STOCK{i}",
                "quantity": i + 1,
                "last_price": float(100 * (i + 1)),
                "pnl": float(10 * i),
            }
            for i in range(n)
        ]
    }


def _kite_holdings_body(n: int = 3) -> dict:
    return {
        "data": [
            {
                "tradingsymbol": f"KITE{i}",
                "quantity": i + 1,
                "last_price": float(200 * (i + 1)),
                "pnl": float(20 * i),
            }
            for i in range(n)
        ]
    }


# ── Upstox ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpstoxSync:
    async def _run_sync_with_body(self, body: dict):
        provider = UpstoxIntegration()
        integration = _make_integration(slug="upstox")
        db = AsyncMock()

        async def _fake_get_access_token(*, integration, db):
            return "upstox_token"

        with patch.object(
            provider, "get_access_token", side_effect=_fake_get_access_token
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_response = MagicMock()
                mock_response.json.return_value = body
                mock_response.raise_for_status.return_value = None
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.get.return_value = mock_response
                mock_client_cls.return_value = mock_client

                await provider.sync(integration=integration, db=db)

        return integration

    async def test_all_four_holding_fields_present(self):
        integration = await self._run_sync_with_body(_upstox_holdings_body(1))
        holdings = integration.config["holdings"]
        assert len(holdings) == 1
        h = holdings[0]
        assert "symbol" in h
        assert "qty" in h
        assert "ltp" in h
        assert "pnl" in h

    async def test_pnl_value_populated(self):
        """pnl was previously missing from Upstox — this is the FEAT-137 fix."""
        integration = await self._run_sync_with_body(_upstox_holdings_body(2))
        holdings = integration.config["holdings"]
        assert holdings[1]["pnl"] == pytest.approx(10.0)

    async def test_max_stored_holdings_bound(self):
        n = MAX_STORED_HOLDINGS + 5  # more than the cap
        integration = await self._run_sync_with_body(_upstox_holdings_body(n))
        assert len(integration.config["holdings"]) == MAX_STORED_HOLDINGS

    async def test_holding_count_reflects_full_portfolio(self):
        n = MAX_STORED_HOLDINGS + 3
        integration = await self._run_sync_with_body(_upstox_holdings_body(n))
        assert integration.config["holding_count"] == n

    async def test_success_sets_connected(self):
        integration = await self._run_sync_with_body(_upstox_holdings_body())
        assert integration.status == "connected"
        assert integration.last_error is None

    async def _run_sync_with_http_error(self, status_code: int):
        provider = UpstoxIntegration()
        integration = _make_integration(slug="upstox")
        db = AsyncMock()

        async def _fake_get_access_token(*, integration, db):
            return "upstox_token"

        with patch.object(
            provider, "get_access_token", side_effect=_fake_get_access_token
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                response = MagicMock(status_code=status_code)
                exc = httpx.HTTPStatusError(
                    str(status_code), request=MagicMock(), response=response
                )
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.get.side_effect = exc
                mock_client_cls.return_value = mock_client

                with pytest.raises(IntegrationError):
                    await provider.sync(integration=integration, db=db)

        return integration

    async def test_401_sets_expired(self):
        integration = await self._run_sync_with_http_error(401)
        assert integration.status == "expired"

    async def test_500_sets_error(self):
        integration = await self._run_sync_with_http_error(500)
        assert integration.status == "error"


# ── Zerodha Kite ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestZerodhaSync:
    async def _run_sync_with_body(self, body: dict):
        provider = ZerodhaKiteIntegration()
        integration = _make_integration(slug="zerodha_kite")
        db = AsyncMock()

        async def _fake_get_access_token(*, integration, db):
            return "kite_access_token"

        with patch.object(
            provider, "get_access_token", side_effect=_fake_get_access_token
        ):
            with patch.object(provider, "_client_id", return_value="kite_api_key"):
                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_response = MagicMock()
                    mock_response.json.return_value = body
                    mock_response.raise_for_status.return_value = None
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.get.return_value = mock_response
                    mock_client_cls.return_value = mock_client

                    await provider.sync(integration=integration, db=db)

        return integration

    async def test_all_four_holding_fields_present(self):
        integration = await self._run_sync_with_body(_kite_holdings_body(1))
        holdings = integration.config["holdings"]
        assert len(holdings) == 1
        h = holdings[0]
        assert "symbol" in h
        assert "qty" in h
        assert "ltp" in h
        assert "pnl" in h

    async def test_pnl_populated_from_broker_response(self):
        integration = await self._run_sync_with_body(_kite_holdings_body(2))
        assert integration.config["holdings"][1]["pnl"] == pytest.approx(20.0)

    async def test_max_stored_holdings_bound(self):
        n = MAX_STORED_HOLDINGS + 5
        integration = await self._run_sync_with_body(_kite_holdings_body(n))
        assert len(integration.config["holdings"]) == MAX_STORED_HOLDINGS

    async def test_holding_count_reflects_full_portfolio(self):
        n = MAX_STORED_HOLDINGS + 3
        integration = await self._run_sync_with_body(_kite_holdings_body(n))
        assert integration.config["holding_count"] == n

    async def test_success_sets_connected(self):
        integration = await self._run_sync_with_body(_kite_holdings_body())
        assert integration.status == "connected"
        assert integration.last_error is None

    async def test_no_refresh_token_sets_expired(self):
        """Primary Zerodha defect: dead daily token (06:00 IST) previously left
        integration.status stuck on 'connected'. no_refresh_token from
        get_access_token must now produce 'expired'.
        """
        provider = ZerodhaKiteIntegration()
        integration = _make_integration(slug="zerodha_kite")
        db = AsyncMock()

        async def _fail_get_access_token(*, integration, db):
            raise IntegrationError("no_refresh_token", "Kite token expired")

        with patch.object(
            provider, "get_access_token", side_effect=_fail_get_access_token
        ):
            with pytest.raises(IntegrationError):
                await provider.sync(integration=integration, db=db)

        assert integration.status == "expired"

    async def _run_sync_with_http_error(self, status_code: int):
        provider = ZerodhaKiteIntegration()
        integration = _make_integration(slug="zerodha_kite")
        db = AsyncMock()

        async def _fake_get_access_token(*, integration, db):
            return "kite_access_token"

        with patch.object(
            provider, "get_access_token", side_effect=_fake_get_access_token
        ):
            with patch.object(provider, "_client_id", return_value="kite_api_key"):
                with patch("httpx.AsyncClient") as mock_client_cls:
                    response = MagicMock(status_code=status_code)
                    exc = httpx.HTTPStatusError(
                        str(status_code), request=MagicMock(), response=response
                    )
                    mock_client = AsyncMock()
                    mock_client.__aenter__.return_value = mock_client
                    mock_client.get.side_effect = exc
                    mock_client_cls.return_value = mock_client

                    with pytest.raises(IntegrationError):
                        await provider.sync(integration=integration, db=db)

        return integration

    async def test_401_sets_expired(self):
        integration = await self._run_sync_with_http_error(401)
        assert integration.status == "expired"

    async def test_500_sets_error(self):
        integration = await self._run_sync_with_http_error(500)
        assert integration.status == "error"


# ── WP-2 regression guard: BrokerHoldings.error never leaks raw exception ─────


class TestSafeErrorMessage:
    """Wire-boundary guard: the client must never receive raw exception text,
    internal URLs, or status codes from integration.last_error.
    """

    def test_expired_status_returns_human_safe_message(self):
        msg = _safe_error_message("expired", "Upstox (India)")
        assert msg is not None
        assert "Reconnect" in msg or "reconnect" in msg.lower()

    def test_error_status_returns_generic_retry_message(self):
        msg = _safe_error_message("error", "Zerodha Kite (India)")
        assert msg is not None
        assert "sync" in msg.lower() or "reach" in msg.lower()

    def test_connected_status_returns_none(self):
        assert _safe_error_message("connected", "Upstox (India)") is None

    def test_expired_message_contains_display_name(self):
        msg = _safe_error_message("expired", "Upstox (India)")
        assert "Upstox" in (msg or "")

    def test_error_message_contains_display_name(self):
        msg = _safe_error_message("error", "Zerodha Kite (India)")
        assert "Zerodha" in (msg or "")

    def test_no_raw_exception_text_in_expired(self):
        """Expired message must not contain exception class names or URLs."""
        raw_error_examples = [
            "IntegrationError",
            "HTTPStatusError",
            "https://api.upstox.com",
            "401",
            "Traceback",
        ]
        msg = _safe_error_message("expired", "Upstox (India)") or ""
        for fragment in raw_error_examples:
            assert fragment not in msg, f"Leaked: {fragment!r} in {msg!r}"

    def test_no_raw_exception_text_in_error(self):
        """Error message must not contain exception class names or URLs."""
        raw_error_examples = [
            "HTTPStatusError",
            "httpx",
            "https://api.kite.trade",
            "500",
            "Traceback",
        ]
        msg = _safe_error_message("error", "Zerodha Kite (India)") or ""
        for fragment in raw_error_examples:
            assert fragment not in msg, f"Leaked: {fragment!r} in {msg!r}"
