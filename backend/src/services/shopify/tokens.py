"""The single seam between the Shopify API layer and the OAuth provider
layer, mirroring src/services/whoop/tokens.py exactly.

Shopify offline access tokens never expire and no refresh token is issued,
so this simply decrypts the stored token — the base class's refresh branch
is dead code for this provider (expires_at and encrypted_refresh_token are
always null). If Shopify ever revokes a token out of band (the merchant
uninstalled the app), a live request returns 401/403 and the router's error
classification marks the integration expired.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration


async def get_access_token(integration: Integration, db: AsyncSession) -> str:
    from ...integrations.personal.shopify import ShopifyIntegration

    return await ShopifyIntegration().get_access_token(integration=integration, db=db)
