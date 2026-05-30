"""Upstox (Indian stockbroker) — OAuth2.

Setup:
  1. https://developer.upstox.com → create app
  2. Set redirect URI to:
     https://arshad-ai.onrender.com/api/v1/integrations/oauth/upstox/callback
  3. Add UPSTOX_CLIENT_ID + UPSTOX_CLIENT_SECRET to Render env vars

Note: Upstox API tokens expire daily at 3:30 AM IST. Sync will refresh
errors as expired and prompt re-auth.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..registry import register
from ._oauth_base import OAuthIntegrationProvider, make_oauth_sync_via_api


@register
class UpstoxIntegration(OAuthIntegrationProvider):
    slug = "upstox"
    display_name = "Upstox (India)"
    category = "Finance"
    description = "Indian stock holdings, orders, market data."
    docs_url = "https://upstox.com/developer/api-documentation/open-api"
    icon = "upstox"
    auth_url = "https://api.upstox.com/v2/login/authorization/dialog"
    token_url = "https://api.upstox.com/v2/login/authorization/token"
    scopes: list[str] = []  # Upstox doesn't use scope query param
    client_id_env = "UPSTOX_CLIENT_ID"
    client_secret_env = "UPSTOX_CLIENT_SECRET"

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.upstox.com/v2/user/profile",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
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

    sync = make_oauth_sync_via_api(
        sync_url="https://api.upstox.com/v2/portfolio/long-term-holdings",
        parse_sync=lambda body: {
            "holding_count": len((body or {}).get("data", [])),
            "holdings": [
                {
                    "symbol": h.get("trading_symbol"),
                    "qty": h.get("quantity"),
                    "ltp": h.get("last_price"),
                }
                for h in (body or {}).get("data", [])[:10]
            ],
        },
        summary_fmt="Upstox: holdings refreshed",
    )
