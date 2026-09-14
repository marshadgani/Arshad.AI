"""Thin binding over src/services/integrations/state.py for the 'shopify'
slug, plus sole ownership of the Shopify Integration.config shape.

Both directions of that shape live here: shop_metadata_config() builds the
keys, shop_context()/shop_presentation() read them. Callers on either side
pass a metadata dict in or take a dataclass out, never a config key, so a
change to the stored shape touches this file alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...integrations.base import IntegrationError
from ...models.integration import Integration
from ..integrations import state as _shared

SHOPIFY_SLUG = "shopify"

REAUTH_CODES = frozenset(
    {
        "refresh_failed",
        "no_refresh_token",
        "not_connected",
        "token_decryption_failed",
        "shopify_shop_missing",
    }
)


async def find_integration(user_id: str, db: AsyncSession) -> Integration | None:
    return await _shared.find_integration(user_id, SHOPIFY_SLUG, db)


def classify_error(exc: Exception) -> tuple[bool, int]:
    return _shared.classify_error(exc, REAUTH_CODES)


apply_error_status = _shared.apply_error_status
mark_healthy = _shared.mark_healthy


def shop_metadata_config(meta: dict[str, Any]) -> dict[str, Any]:
    """Shop metadata (as returned by services/shopify/client.py) -> the
    Integration.config keys read below.

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


def shop_domain(integration: Integration) -> str:
    domain = (integration.config or {}).get("shop_domain")
    if not domain:
        raise IntegrationError(
            "shopify_shop_missing",
            "No shop domain stored on this integration. Reconnect Shopify.",
        )
    return domain


@dataclass(frozen=True)
class ShopPresentation:
    """Stored shop labels, exactly as persisted — no defaults applied.

    Backs the degraded response shape, which must report what is actually
    known about the shop rather than inventing 'UTC'/'USD' for a record
    whose metadata probe never succeeded.
    """

    shop_name: str | None
    currency_code: str | None
    timezone: str | None


@dataclass(frozen=True)
class ShopContext:
    """Everything a live read needs from the stored integration record.

    Resolved once per request so the router and the read-model assembler
    pass one value around instead of four independent config lookups.
    Timezone and currency are defaulted here because a live read has to
    pick *some* calendar day and *some* currency to render.
    """

    shop: str
    timezone: str
    currency_code: str
    shop_name: str | None


def shop_presentation(integration: Integration) -> ShopPresentation:
    """Never raises — safe on a partially-populated integration record."""
    config = integration.config or {}
    return ShopPresentation(
        shop_name=config.get("shop_name"),
        currency_code=config.get("currency_code"),
        timezone=config.get("shop_timezone"),
    )


def shop_context(integration: Integration) -> ShopContext:
    """Build a ShopContext, raising 'shopify_shop_missing' when the shop
    domain is absent.

    Deliberately NOT usable for the degraded/reauth response shape — that
    path must never raise, so it uses shop_presentation() instead (see
    dashboard.shell_dashboard).
    """
    presentation = shop_presentation(integration)
    return ShopContext(
        shop=shop_domain(integration),
        timezone=presentation.timezone or "UTC",
        currency_code=presentation.currency_code or "USD",
        shop_name=presentation.shop_name,
    )
