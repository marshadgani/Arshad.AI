"""Plaid (US banking) — integration lifecycle (connect -> sync -> status).

Plaid uses a 4-step token flow:
  1. Frontend calls /link/token/create to get a `link_token`
  2. User completes Plaid Link UI → frontend gets a `public_token`
  3. Backend exchanges public_token → access_token (long-lived)
  4. Backend calls /accounts/get with access_token

Only step 4's /accounts/get is implemented. There is deliberately no
/transactions/get call anywhere in this package: sync() refreshes account
balances and nothing else. Do not describe this provider as delivering
transactions until a transactions read path actually exists.

For Phase H wave 4, this provider supports the public_token-exchange path.
The user pastes a public_token they obtained from Plaid Link
(Plaid's quickstart sandbox tool, or a frontend Link integration).

connect() also accepts {api_key: "access-<env>-..."} directly, for
sandbox/quickstart access_tokens obtained outside Link. That path is
format- and env-validated at connect time, before the token is ever stored.

Phase J will add a proper Link button to the Integrations UI that fetches
a link_token from /api/v1/integrations/plaid/link-token, runs Plaid Link,
and POSTs the resulting public_token to /connect — turning this from a
paste-public-token flow into a 1-click flow.

This module holds the lifecycle only. Its two neighbours:
  - plaid_tokens.py  — pure credential-shape rules (no I/O, no env)
  - plaid_client.py  — Plaid environment, URLs, HTTP calls, response shaping
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import decrypt
from ...models.integration import ApiKeyCredential, Integration
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
    revokes_via,
    safe_detail,
)
from ..project._shared import (
    mark_error,
    mark_synced,
    project_status,
    require_api_key,
    store_api_key,
)
from ..registry import register
from . import plaid_client, plaid_tokens

# Recorded on the credential row and echoed back as extra["scopes"], so it is
# a claim about this integration's reach. "transactions:read" was listed here
# while no code ever read a transaction; kept to what sync() actually
# exercises rather than what the provider might one day grow into.
_SCOPES = ["accounts:read"]

# Integration.config keys holding the account snapshot sync() writes. Not
# credentials, so services/integration_credentials.scrub_credentials() does
# not touch them — but they are bank account names and balances, and
# "disconnect my bank" must not leave those behind. Cleared by disconnect().
_ACCOUNT_SNAPSHOT_KEYS = frozenset({"accounts", "account_count"})


def _validate_access_token(key: str) -> str:
    """Bind plaid_tokens' pure rule to the environment plaid_client resolves.

    The single point where those two modules meet, so neither imports the
    other.
    """
    return plaid_tokens.validate_access_token(
        key, configured_env=plaid_client.plaid_env()
    )


@register
class PlaidIntegration(IntegrationProvider):
    slug = "plaid"
    kind = "personal_apikey"  # treated as per-user key (the access_token)
    display_name = "Plaid (US Banking)"
    category = "Finance"
    # Describes what sync() actually fetches (/accounts/get — accounts and
    # their balances). It previously also promised "transactions", which no
    # code path has ever delivered; unlike Shopify's dashboard, there is no
    # live-read endpoint serving them either. Pinned by a test — see
    # test_plaid_integration.test_description_does_not_promise_transactions.
    description = "US bank accounts and balances via Plaid Link."
    docs_url = "https://plaid.com/docs/"
    icon = "plaid"
    upstream_revocation = revokes_via(
        "POST /item/remove — Plaid unlinks your bank Item, so the "
        "connection is closed on Plaid's side, not just forgotten here."
    )

    async def _revoke_upstream(
        self, *, integration: Integration, db: AsyncSession
    ) -> None:
        """Remove the Plaid Item before the local access_token is deleted.

        Ordering is the point: /item/remove is the only call that can
        invalidate this credential, and it needs the access_token we are
        about to destroy. base.disconnect() runs this first for exactly
        that reason.

        A backend missing PLAID_CLIENT_ID/PLAID_SECRET raises
        IntegrationError here rather than being pre-checked, because on
        the disconnect path an unusable backend config must not stop the
        local deletion — disconnect() logs it and carries on, which is
        the correct outcome for a user who asked us to forget their
        banking credential.
        """
        access_token = await self._stored_access_token(integration=integration, db=db)
        await plaid_client.remove_item(access_token)

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        """Expects payload to be EITHER:
        {public_token: "..."} → exchange for access_token, OR
        {api_key: "access-..."} → user pasted a sandbox access_token directly
        """
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        payload = payload or {}

        if payload.get("public_token"):
            return await self._connect_via_link(
                public_token=payload["public_token"], user=user, db=db
            )

        if payload.get("api_key"):
            return await self._connect_via_pasted_token(
                payload=payload, user=user, db=db
            )

        raise IntegrationError(
            "missing_token",
            "Provide either {public_token} from Plaid Link or {api_key} "
            "(a Plaid access_token).",
        )

    async def _connect_via_link(
        self, *, public_token: str, user: User, db: AsyncSession
    ) -> ConnectResult:
        exchange = await plaid_client.exchange_public_token(public_token)
        return await self._store(
            db=db,
            user=user,
            access_token=exchange.access_token,
            extra={"item_id": exchange.item_id, "env": plaid_client.plaid_env()},
        )

    async def _connect_via_pasted_token(
        self, *, payload: dict[str, Any], user: User, db: AsyncSession
    ) -> ConnectResult:
        # Refuse a paste the deployment could never use anyway.
        plaid_client.require_backend_config()
        # Shape only — no network call. Liveness and authorisation are proven
        # by the first sync(), which is the first call to present this token.
        key = _validate_access_token(require_api_key(payload))
        return await self._store(
            db=db,
            user=user,
            access_token=key,
            extra={"env": plaid_client.plaid_env(), "source": "direct_paste"},
        )

    async def _store(
        self,
        *,
        db: AsyncSession,
        user: User,
        access_token: str,
        extra: dict[str, Any],
    ) -> ConnectResult:
        return await store_api_key(
            db=db,
            slug=self.slug,
            api_key=access_token,
            extra=extra,
            scopes=_SCOPES,
            user_id=user.id,
            kind="personal_apikey",
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        access_token = await self._stored_access_token(integration=integration, db=db)
        # Resolved before the try: a backend misconfiguration is a deployment
        # fault, not this user's integration failing, and must not be written
        # to their Integration row as a sync error.
        plaid_client.require_backend_config()
        try:
            accounts = await plaid_client.fetch_accounts(access_token)
        except Exception as exc:  # noqa: BLE001
            # safe_detail, not str(exc): this message becomes the 400 body of
            # POST /api/v1/integrations/plaid/sync, and httpx embeds the full
            # request URL in every HTTPStatusError/RequestError message. Same
            # rule mark_error() already applies to integration.last_error.
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", safe_detail(exc)) from exc

        integration.config = {
            **(integration.config or {}),
            "account_count": len(accounts),
            "accounts": plaid_client.account_summaries(accounts),
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f"Plaid: {len(accounts)} account(s) refreshed.",
            started=started,
        )

    async def disconnect(
        self, *, integration: Integration, db: AsyncSession
    ) -> None:
        """Delete the credential (base class), then drop the account snapshot.

        base.disconnect() scrubs *credentials*; the account names, types and
        balances sync() caches in Integration.config are bank data, not
        credentials, so nothing else removes them. Leaving them behind after
        a user asks us to forget their bank connection would keep cleartext
        financial detail in Postgres indefinitely, with no consumer and no
        way for the user to clear it.

        Runs after super() so that a failure here cannot leave the
        credential in place, and commits separately because base.disconnect()
        has already closed its transaction.
        """
        await super().disconnect(integration=integration, db=db)
        config = {
            k: v
            for k, v in (integration.config or {}).items()
            if k not in _ACCOUNT_SNAPSHOT_KEYS
        }
        if config != (integration.config or {}):
            integration.config = config
            await db.commit()

    @staticmethod
    async def _stored_access_token(
        *, integration: Integration, db: AsyncSession
    ) -> str:
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "Plaid access_token not stored.")
        return decrypt(creds.encrypted_key)

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
