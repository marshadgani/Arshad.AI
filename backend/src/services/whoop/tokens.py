"""The single seam between the Whoop API layer and the OAuth provider layer.

The router previously reached into
`integrations.personal.oauth_providers.WhoopIntegration` through a
function-body import — a deferred import used to dodge an import cycle,
which hid the fact that the HTTP layer was coupled to a concrete provider
implementation.

Narrowing that to one function in one module means the router depends on
"get me a Whoop access token", not on the provider class. The import stays
deferred (oauth_providers imports the integrations registry, which imports
every provider module) but is now confined to a single documented place
instead of leaking into request handlers.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration


async def get_access_token(integration: Integration, db: AsyncSession) -> str:
    """Return a usable Whoop access token, refreshing it if required.

    Raises IntegrationError with one of state.REAUTH_CODES when the token
    cannot be refreshed without the user re-approving access.
    """
    from ...integrations.personal.oauth_providers import WhoopIntegration

    return await WhoopIntegration().get_access_token(integration=integration, db=db)
