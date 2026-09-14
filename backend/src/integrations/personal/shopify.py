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

Shopify has no public token-revocation endpoint — the merchant must
uninstall the app from the Shopify admin to fully revoke the token.
disconnect() therefore uses the base class default, which deletes the
stored IntegrationOAuthToken row and marks the integration disconnected.
It also deliberately does not touch the dashboard cache: the read path checks
find_integration() before ever consulting cache, so a disconnected
integration's cache entry is unreachable and expires within 120s on its own
— touching Redis from this layer would be an unnecessary L3->L2 dependency.

read_orders exposes only the last 60 days of history for non-Plus apps —
this module is a live read model, not an ingestion pipeline, and historical
revenue analysis beyond 60 days must not be built on this foundation.

This module holds the OAuth *lifecycle* only. Its two neighbours:
  - shopify_oauth.py       — pure shop-domain and callback verification rules
  - services/shopify/*     — HTTP transport, parsing, caching, config shape

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

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    StatusReport,
    SyncResult,
    cannot_revoke,
    safe_detail,
)
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


@register
class ShopifyIntegration(OAuthIntegrationProvider):
    slug = "shopify"
    display_name = "Shopify"
    category = "Commerce"
    # Describes GET /api/v1/shopify/dashboard, not sync() — see sync().
    description = (
        "Live orders, revenue, and inventory from your Shopify store dashboard."
    )
    docs_url = "https://shopify.dev/docs/apps/build/authentication-authorization"
    icon = "shopify"
    connect_prompt = {
        "label": "Shopify Store Domain",
        "placeholder": "my-store.myshopify.com",
    }
    # Shopify publishes no token-revocation endpoint; an offline access
    # token stays valid until the app is uninstalled from the store. See
    # the module docstring.
    upstream_revocation = cannot_revoke(
        "Shopify provides no token-revocation API — an app's access token "
        "stays valid until the app is uninstalled. Uninstall Arshad.AI from "
        "your Shopify admin (Settings → Apps) to revoke it on Shopify's side."
    )

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

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
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
        from ...services.shopify import state as shopify_state

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
            config_extra={
                "shop_domain": stored_shop,
                **shopify_state.shop_metadata_config(meta),
            },
        )

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        # No-op: all shop metadata is fetched inside complete_callback().
        return {}

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        """Refresh stored shop metadata.

        rows_written is 0 by design: orders, revenue and inventory are read
        live per dashboard request (see services/shopify/dashboard.py) and
        are never ingested here.
        """
        from ...services.shopify import client as shopify_client
        from ...services.shopify import state as shopify_state

        started = time.perf_counter()
        access_token = await self.get_access_token(integration=integration, db=db)
        shop = shopify_state.shop_domain(integration)
        try:
            meta = await shopify_client.fetch_shop_metadata(shop, access_token)
        except Exception as exc:  # noqa: BLE001
            await self._record_sync_failure(integration, exc, db)

        await self._record_metadata_refresh(integration, meta, db)

        return SyncResult(
            rows_written=0,
            summary=f"Refreshed shop metadata for {shop}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    async def _record_metadata_refresh(
        integration: Integration, meta: dict[str, Any], db: AsyncSession
    ) -> None:
        """Persist a successful refresh — the counterpart to _record_sync_failure."""
        from ...services.shopify import cache as shopify_cache
        from ...services.shopify import state as shopify_state

        integration.config = {
            **(integration.config or {}),
            **shopify_state.shop_metadata_config(meta),
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        # Metadata the dashboard renders (name/currency/timezone) just
        # changed, so the cached payload built from the old values is stale.
        await shopify_cache.del_dashboard_cache(str(integration.id))

    @staticmethod
    async def _record_sync_failure(
        integration: Integration, exc: Exception, db: AsyncSession
    ) -> NoReturn:
        """Persist the failed-sync status, then re-raise as sync_failed.

        NoReturn is load-bearing: sync() relies on this never falling
        through, so the value it was computing stays definitely-assigned.

        Both the persisted status and the raised message carry
        ``safe_detail(exc)``, never ``str(exc)``: ``integration.last_error``
        is returned verbatim by GET /api/v1/integrations/shopify/status and
        the raised message becomes the 400 body of POST /{slug}/sync, while
        httpx embeds the full request URL in the message of every
        HTTPStatusError/RequestError. See base.safe_detail and
        tests/test_integration_error_leakage.py — this provider was the last
        personal integration still on the leaky shape.
        """
        # Logged in addition to the DB write: the deployment verification
        # protocol (CLAUDE.md §23) diagnoses production issues by grepping
        # Render app logs for warning/error lines, not by querying Postgres
        # — a failure recorded only in integration.last_error is invisible
        # to that workflow. The log gets the full exception; only the
        # operator can read it.
        _log.warning(
            "Shopify sync failed for integration_id=%s", integration.id, exc_info=exc
        )
        integration.status = "error"
        integration.last_error = safe_detail(exc)[:_LAST_ERROR_MAX_CHARS]
        await db.commit()
        raise IntegrationError("sync_failed", safe_detail(exc)) from exc

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        report = await super().status(integration=integration, db=db)
        config = integration.config or {}
        report.extra.update(
            {
                "shop_domain": config.get("shop_domain"),
                "currency_code": config.get("currency_code"),
            }
        )
        return report
