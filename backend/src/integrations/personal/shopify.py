"""Shopify Admin API — OAuth2, per-shop.

Shopify's OAuth flow is per-shop, not a single fixed auth_url like every
other provider in oauth_providers.py:
  - Auth URL:  https://{shop}/admin/oauth/authorize?client_id=...
  - Token URL: https://{shop}/admin/oauth/access_token
  - Callbacks are HMAC-signed with the client secret and must be verified.

The shop domain comes from the user at connect time (payload['shop']),
is validated, and is stored in the OAuth state's Redis-bound context —
never trusted from the callback query string, which an attacker fully
controls. All subsequent URLs (token exchange, shop-metadata probe) are
built exclusively from that Redis-stored value.

Setup:
  1. Register a Partner app at https://partners.shopify.com
  2. Redirect URI: https://arshad-ai.onrender.com/api/v1/integrations/oauth/shopify/callback
  3. Add SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET to Render env vars.

Shopify offline access tokens never expire and no refresh token is issued;
expires_at and encrypted_refresh_token are always null, so
OAuthIntegrationProvider.get_access_token() falls straight through to
decrypt() without entering the refresh branch.

Shopify has no public token-revocation endpoint — revocation happens only
when the merchant uninstalls the app from the Shopify admin. disconnect()
therefore uses the base class default (marks the row disconnected locally)
and deliberately does not touch the dashboard cache: the read path checks
find_integration() before ever consulting cache, so a disconnected
integration's cache entry is unreachable and expires within 120s on its own
— touching Redis from this layer would be an unnecessary L3->L2 dependency.

read_orders exposes only the last 60 days of history for non-Plus apps —
this module is a live read model, not an ingestion pipeline, and historical
revenue analysis beyond 60 days must not be built on this foundation.

This module holds the OAuth *lifecycle* only. Its two neighbours:
  - shopify_oauth.py       — pure shop-domain and callback verification rules
  - services/shopify/*     — HTTP transport, parsing, caching, state

Imports of services.shopify are deliberately function-local. src.services.
shopify.client imports integrations.base, which executes
integrations/__init__.py, which imports this module — a module-level import
in the other direction would close that cycle. The deferred import is the
seam that keeps the two packages independently importable, the same device
used by services/shopify/tokens.py in the opposite direction.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, NoReturn
from urllib.parse import urlencode

from ..base import ConnectResult, IntegrationError, StatusReport, SyncResult
from ..registry import register
from . import shopify_oauth
from ._oauth_base import (
    CallbackOutcome,
    OAuthCallbackContext,
    OAuthIntegrationProvider,
    store_oauth_state,
)

_LAST_ERROR_MAX_CHARS = 500

_log = logging.getLogger(__name__)


def _shop_metadata_config(meta: dict[str, Any]) -> dict[str, Any]:
    """Shop metadata -> the Integration.config keys read by
    services/shopify/state.py.

    One writer for those keys, shared by the OAuth callback and sync, so the
    two cannot drift apart in what they persist. The defaults are applied
    here rather than at read time so a shop whose metadata probe failed
    still lands with a usable timezone/currency.
    """
    return {
        "shop_timezone": meta.get("ianaTimezone") or "UTC",
        "currency_code": meta.get("currencyCode") or "USD",
        "shop_name": meta.get("name"),
    }


@register
class ShopifyIntegration(OAuthIntegrationProvider):
    slug = "shopify"
    display_name = "Shopify"
    category = "Commerce"
    description = "Live orders, revenue, and inventory from your Shopify store."
    docs_url = "https://shopify.dev/docs/apps/build/authentication-authorization"
    icon = "shopify"
    connect_prompt = {
        "label": "Shopify Store Domain",
        "placeholder": "my-store.myshopify.com",
    }

    # OAuthIntegrationProvider ClassVars — auth_url/token_url are built
    # per-shop below, so these are placeholders that are never dereferenced.
    auth_url = ""
    token_url = ""
    scopes: list[str] = [
        "read_orders",
        "read_products",
        "read_inventory",
        "read_locations",
        "read_reports",
    ]
    client_id_env = "SHOPIFY_CLIENT_ID"
    client_secret_env = "SHOPIFY_CLIENT_SECRET"

    async def connect(self, *, user, db, payload):  # type: ignore[override]
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        shop = shopify_oauth.validate_shop_domain((payload or {}).get("shop"))
        # Surface a missing-credentials error before redirecting the browser.
        client_id = self._client_id()
        self._client_secret()
        state = await store_oauth_state(
            user_id=str(user.id), slug=self.slug, ctx={"shop": shop}
        )
        params = {
            "client_id": client_id,
            "scope": self.scope_separator.join(self.scopes),
            "redirect_uri": self._redirect_uri(),
            "state": state,
        }
        url = f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"
        return ConnectResult(integration_id=None, redirect_url=url)

    async def complete_callback(
        self, *, context: OAuthCallbackContext
    ) -> CallbackOutcome:
        from ...services.shopify import client as shopify_client

        stored_shop = context.stored.get("shop")
        if not stored_shop:
            raise IntegrationError(
                "shopify_shop_missing", "No shop domain found for this OAuth attempt."
            )

        client_secret = self._client_secret()
        shopify_oauth.verify_callback(
            query_params=context.query_params,
            stored_shop=stored_shop,
            client_secret=client_secret,
        )

        token_response = await shopify_client.exchange_oauth_code(
            shop=stored_shop,
            client_id=self._client_id(),
            client_secret=client_secret,
            code=context.code,
        )

        try:
            meta = await shopify_client.fetch_shop_metadata(
                stored_shop, token_response["access_token"]
            )
        except Exception as exc:  # noqa: BLE001 — metadata probe is best-effort
            # Best-effort by design (a failed probe must not fail the whole
            # connect flow), but "best-effort" must still be observable:
            # without this log, a missing scope, timeout, or malformed
            # response leaves the integration connected with silently
            # defaulted UTC/USD and nothing in the Render logs to explain
            # why — undebuggable per the project's deployment verification
            # protocol, which greps app logs for warning/error lines.
            _log.warning(
                "Shopify shop-metadata probe failed during connect for shop=%s: %s: %s",
                stored_shop,
                type(exc).__name__,
                exc,
            )
            meta = {}

        return CallbackOutcome(
            token_response=token_response,
            profile={},
            config_extra={"shop_domain": stored_shop, **_shop_metadata_config(meta)},
        )

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        # No-op: all shop metadata is fetched inside complete_callback().
        return {}

    async def sync(self, *, integration, db):  # type: ignore[override]
        from ...services.shopify import cache as shopify_cache
        from ...services.shopify import client as shopify_client
        from ...services.shopify import state as shopify_state

        started = time.perf_counter()
        access_token = await self.get_access_token(integration=integration, db=db)
        shop = shopify_state.shop_domain(integration)
        try:
            meta = await shopify_client.fetch_shop_metadata(shop, access_token)
        except Exception as exc:  # noqa: BLE001
            await self._record_sync_failure(integration, exc, db)

        integration.config = {
            **(integration.config or {}),
            **_shop_metadata_config(meta),
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        # Metadata the dashboard renders (name/currency/timezone) just
        # changed, so the cached payload built from the old values is stale.
        await shopify_cache.del_dashboard_cache(str(integration.id))

        return SyncResult(
            rows_written=0,
            summary=f"Refreshed shop metadata for {shop}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    async def _record_sync_failure(integration, exc: Exception, db) -> NoReturn:  # type: ignore[no-untyped-def]
        """Persist the failed-sync status, then re-raise as sync_failed.

        NoReturn is load-bearing: sync() relies on this never falling
        through, so the value it was computing stays definitely-assigned.
        """
        # Logged in addition to the DB write: the deployment verification
        # protocol (CLAUDE.md §23) diagnoses production issues by grepping
        # Render app logs for warning/error lines, not by querying Postgres
        # — a failure recorded only in integration.last_error is invisible
        # to that workflow.
        _log.warning(
            "Shopify sync failed for integration_id=%s: %s: %s",
            integration.id,
            type(exc).__name__,
            exc,
        )
        integration.status = "error"
        integration.last_error = f"{type(exc).__name__}: {exc}"[:_LAST_ERROR_MAX_CHARS]
        await db.commit()
        raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")

    async def status(self, *, integration, db) -> StatusReport:  # type: ignore[override]
        report = await super().status(integration=integration, db=db)
        config = integration.config or {}
        report.extra.update(
            {
                "shop_domain": config.get("shop_domain"),
                "currency_code": config.get("currency_code"),
            }
        )
        return report
