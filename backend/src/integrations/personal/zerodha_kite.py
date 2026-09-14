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

from ..base import ConnectResult, IntegrationError, revokes_via
from ..registry import register
from ._oauth_base import (
    OAuthIntegrationProvider,
    store_oauth_state,
)


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
    upstream_revocation = revokes_via(
        "DELETE https://api.kite.trade/session/token — Kite invalidates the "
        "session, so the token stops working before its usual end-of-day "
        "expiry."
    )

    async def _revoke_upstream(self, *, integration, db) -> None:  # type: ignore[override]
        """Kite's logout is a DELETE on the session with BOTH the api_key
        and the access_token in the query string — it is not RFC 7009 and
        not bearer-authenticated, so it does not fit any `revoke_style`.

        Adding a fifth style for a single provider would push
        Kite-specific knowledge into the shared base; overriding here
        keeps it in the one module that already knows Kite's checksum
        auth and `token <api_key>:<access_token>` header format. Credential
        reading still goes through the base's _stored_tokens(), so the
        decrypt and no-row-yet cases stay handled in one place.

        Errors propagate — disconnect() logs them and deletes the local
        rows regardless — but only as an IntegrationError naming the
        status code. The access token is in this request's *query string*,
        and httpx puts the full URL in its exception messages, so an
        escaping httpx error would be written verbatim into the log line
        disconnect() emits with exc_info=True. Same rule as
        _oauth_base._post_revocation() and base.safe_detail().
        """
        tokens = await self._stored_tokens(integration=integration, db=db)
        if tokens is None:
            return None
        access_token, _ = tokens
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    "https://api.kite.trade/session/token",
                    params={"api_key": self._client_id(), "access_token": access_token},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise IntegrationError(
                "revoke_failed",
                f"Kite revocation returned {exc.response.status_code}.",
            ) from None
        except httpx.HTTPError as exc:
            raise IntegrationError(
                "revoke_failed", f"Kite revocation failed: {type(exc).__name__}."
            ) from None

    async def connect(self, *, user, db, payload):  # type: ignore[override]
        """Kite uses 'api_key' not 'client_id' in the auth URL."""
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        self._client_id()
        self._client_secret()
        state = await store_oauth_state(user_id=str(user.id), slug=self.slug)
        params = {
            "api_key": self._client_id(),
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

    async def sync(self, *, integration, db):  # type: ignore[override]
        import time
        from datetime import datetime, timezone

        from ..base import IntegrationError as _IE
        from ..base import SyncResult

        started = time.perf_counter()
        access_token = await self.get_access_token(integration=integration, db=db)
        api_key = self._client_id()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.kite.trade/portfolio/holdings",
                    headers={
                        "Authorization": f"token {api_key}:{access_token}",
                        "X-Kite-Version": "3",
                    },
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            integration.status = "error"
            integration.last_error = f"{type(exc).__name__}: {exc}"[:500]
            await db.commit()
            raise _IE("sync_failed", f"{type(exc).__name__}: {exc}")
        holdings = body.get("data") or []
        integration.config = {
            **(integration.config or {}),
            "holding_count": len(holdings),
            "holdings": [
                {
                    "symbol": h.get("tradingsymbol"),
                    "qty": h.get("quantity"),
                    "ltp": h.get("last_price"),
                    "pnl": h.get("pnl"),
                }
                for h in holdings[:10]
            ],
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=f"Kite: {len(holdings)} holdings refreshed",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
