"""Zerodha Kite Connect (Indian stockbroker) — OAuth2.

Kite Connect uses a slightly non-standard OAuth flow:
  - Auth URL accepts api_key= rather than client_id=
  - Token endpoint: POST /session/token with api_key, request_token, checksum
  - checksum = SHA256(api_key + request_token + api_secret)

We override exchange_code() to handle the checksum requirement.

Setup:
  1. Subscribe to Kite Connect (~₹2000/mo) at https://kite.trade
  2. Create app, set redirect URI to:
     https://arshad-ai.onrender.com/api/v1/integrations/oauth/zerodha_kite/callback
  3. Add ZERODHA_KITE_CLIENT_ID (the api_key) + ZERODHA_KITE_CLIENT_SECRET (api_secret)

Tokens expire daily at 6 AM IST.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import ConnectResult, IntegrationError
from ..registry import register
from ._holdings_snapshot import make_holdings_parser
from ._oauth_base import (
    OAuthIntegrationProvider,
    make_oauth_sync_via_api,
    store_oauth_state,
)

# Kite's names for the four snapshot fields -- the only way its portfolio
# read differs from Upstox's in shape. See _holdings_snapshot.py.
_parse_holdings = make_holdings_parser(
    fields={
        "symbol": "tradingsymbol",
        "qty": "quantity",
        "ltp": "last_price",
        "pnl": "pnl",
    }
)


def _holdings_summary(_display_name: str, config_update: dict[str, Any]) -> str:
    """Kite's sync summary quotes the portfolio size, unlike every other
    provider's fixed string -- hence a callable rather than a format str.
    The display name is part of the Summarise signature but unused: "Kite"
    reads better here than the full "Zerodha Kite (India)".
    """
    return f"Kite: {config_update['holding_count']} holdings refreshed"


@register
class ZerodhaKiteIntegration(OAuthIntegrationProvider):
    slug = "zerodha_kite"
    display_name = "Zerodha Kite (India)"
    category = "Finance"
    description = "Indian stock holdings + orders via Kite Connect."
    docs_url = "https://kite.trade/docs/connect/v3/"
    icon = "kite"
    auth_url = "https://kite.zerodha.com/connect/login"
    token_url = "https://api.kite.trade/session/token"
    scopes: list[str] = []
    client_id_env = "ZERODHA_KITE_CLIENT_ID"
    client_secret_env = "ZERODHA_KITE_CLIENT_SECRET"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        """Kite uses 'api_key' not 'client_id' in the auth URL."""
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        api_key = self._client_id()
        # Not used until exchange_code(), but read here so a missing secret
        # fails before the user is sent through Kite's consent screen.
        self._client_secret()
        state = await store_oauth_state(user_id=str(user.id), slug=self.slug)
        params = {
            "api_key": api_key,
            "v": "3",
            "redirect_params": f"state={state}",
        }
        url = f"{self.auth_url}?{urlencode(params)}"
        return ConnectResult(integration_id=None, redirect_url=url)

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Kite uses request_token + checksum, not the standard OAuth2 grant.
        `code` from the callback is actually a `request_token`.
        """
        api_key = self._client_id()
        api_secret = self._client_secret()
        checksum = hashlib.sha256(
            f"{api_key}{code}{api_secret}".encode("utf-8")
        ).hexdigest()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.token_url,
                data={
                    "api_key": api_key,
                    "request_token": code,
                    "checksum": checksum,
                },
                headers={
                    "X-Kite-Version": "3",
                    "Accept": "application/json",
                },
            )
        if resp.status_code >= 400:
            raise IntegrationError(
                "token_exchange_failed",
                f"Kite token exchange returned {resp.status_code}: {resp.text[:200]}",
            )
        body = resp.json() or {}
        if body.get("status") != "success":
            raise IntegrationError(
                "kite_error",
                f"Kite returned status={body.get('status')}: {body.get('message', '')}",
            )
        data = body.get("data") or {}
        # Map Kite's response shape into the OAuth2 shape our base class expects
        return {
            "access_token": data.get("access_token"),
            "refresh_token": None,  # Kite doesn't issue refresh tokens
            "expires_in": None,  # Tokens expire at 6 AM IST daily
            "user_id": data.get("user_id"),
            "user_name": data.get("user_name"),
        }

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        api_key = self._client_id()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.kite.trade/user/profile",
                headers={
                    "Authorization": f"token {api_key}:{access_token}",
                    "X-Kite-Version": "3",
                },
            )
            resp.raise_for_status()
            body = resp.json() or {}
        data = body.get("data") or {}
        return {
            "user_id": data.get("user_id"),
            "user_name": data.get("user_name"),
            "email": data.get("email"),
            "broker": data.get("broker"),
        }

    def sync_headers(self, access_token: str) -> dict[str, str]:
        """Kite authenticates portfolio reads with `token <api_key>:<token>`
        rather than a bearer, and requires its API version header.

        make_oauth_sync_via_api calls this inside its guarded block, which
        is what keeps _client_id() -- IntegrationError('missing_client_id')
        when ZERODHA_KITE_CLIENT_ID is unset or rotated on Render -- inside
        record_sync_failure's reach. Outside it, that error escaped
        classification and left integration.status stuck on 'connected'
        with a stale last_error, the exact defect class this feature closes.
        """
        return {
            "Authorization": f"token {self._client_id()}:{access_token}",
            "X-Kite-Version": "3",
        }

    # Kite issues no refresh token, so a dead daily token (06:00 IST)
    # surfaces as IntegrationError('no_refresh_token') from the preflight
    # get_access_token call inside make_oauth_sync_via_api -- classified
    # there as 'expired' rather than leaving status stuck on 'connected'.
    sync = make_oauth_sync_via_api(
        sync_url="https://api.kite.trade/portfolio/holdings",
        parse_sync=_parse_holdings,
        summarise=_holdings_summary,
    )
