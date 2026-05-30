"""Plaid (US banking) — Link SDK token exchange.

Plaid uses a 2-step token flow:
  1. Frontend calls /link/token/create to get a `link_token`
  2. User completes Plaid Link UI → frontend gets a `public_token`
  3. Backend exchanges public_token → access_token (long-lived)
  4. Backend calls /accounts/get + /transactions/get with access_token

For Phase H wave 4, this provider supports the public_token-exchange path.
The user pastes a public_token they obtained from Plaid Link
(Plaid's quickstart sandbox tool, or a frontend Link integration).

Phase J will add a proper Link button to the Integrations UI that fetches
a link_token from /api/v1/integrations/plaid/link-token, runs Plaid Link,
and POSTs the resulting public_token to /connect — turning this from a
paste-public-token flow into a 1-click flow.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
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
)
from ..project._shared import (
    mark_error,
    mark_synced,
    project_status,
    store_api_key,
)
from ..registry import register


def _plaid_env() -> str:
    return os.getenv("PLAID_ENV", "sandbox")  # sandbox | development | production


def _plaid_base_url() -> str:
    return f"https://{_plaid_env()}.plaid.com"


def _plaid_creds() -> dict[str, str]:
    cid = os.getenv("PLAID_CLIENT_ID")
    secret = os.getenv("PLAID_SECRET")
    if not cid or not secret:
        raise IntegrationError(
            "plaid_not_configured",
            "PLAID_CLIENT_ID and PLAID_SECRET must be set on the backend. "
            "Sign up at https://dashboard.plaid.com/signup.",
        )
    return {"client_id": cid, "secret": secret}


@register
class PlaidIntegration(IntegrationProvider):
    slug = "plaid"
    kind = "personal_apikey"  # treated as per-user key (the access_token)
    display_name = "Plaid (US Banking)"
    category = "Finance"
    description = "US bank accounts, balances, transactions via Plaid Link."
    docs_url = "https://plaid.com/docs/"
    icon = "plaid"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        """Expects payload to be EITHER:
        {public_token: "..."} → exchange for access_token, OR
        {api_key: "access-..."} → user pasted a sandbox access_token directly
        """
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        public_token = (payload or {}).get("public_token")
        api_key = (payload or {}).get("api_key")

        if public_token:
            creds = _plaid_creds()
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{_plaid_base_url()}/item/public_token/exchange",
                        json={**creds, "public_token": public_token},
                    )
                if resp.status_code >= 400:
                    raise IntegrationError(
                        "exchange_failed",
                        f"Plaid token exchange returned {resp.status_code}: {resp.text[:200]}",
                    )
                body = resp.json() or {}
            except IntegrationError:
                raise
            except httpx.HTTPError as exc:
                raise IntegrationError(
                    "plaid_unreachable", f"Plaid API unreachable: {type(exc).__name__}"
                )
            access_token = body.get("access_token")
            item_id = body.get("item_id")
            if not access_token:
                raise IntegrationError(
                    "no_access_token", "Plaid response missing access_token."
                )
            return await store_api_key(
                db=db,
                slug=self.slug,
                api_key=access_token,
                extra={"item_id": item_id, "env": _plaid_env()},
                scopes=["accounts:read", "transactions:read"],
                user_id=user.id,
                kind="personal_apikey",
            )

        if api_key:
            # Direct paste path — usually a sandbox access_token starting "access-sandbox-".
            # No probe call (would consume Plaid quota); validate on first sync.
            return await store_api_key(
                db=db,
                slug=self.slug,
                api_key=api_key,
                extra={"env": _plaid_env(), "source": "direct_paste"},
                scopes=["accounts:read", "transactions:read"],
                user_id=user.id,
                kind="personal_apikey",
            )

        raise IntegrationError(
            "missing_token",
            "Provide either {public_token} from Plaid Link or {api_key} (a Plaid access_token).",
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "Plaid access_token not stored.")
        access_token = decrypt(creds.encrypted_key)
        plaid_creds = _plaid_creds()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{_plaid_base_url()}/accounts/get",
                    json={**plaid_creds, "access_token": access_token},
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        accounts = body.get("accounts") or []
        integration.config = {
            **(integration.config or {}),
            "account_count": len(accounts),
            "accounts": [
                {
                    "id": a.get("account_id"),
                    "name": a.get("name"),
                    "type": a.get("type"),
                    "balance": (a.get("balances") or {}).get("current"),
                    "currency": (a.get("balances") or {}).get("iso_currency_code"),
                }
                for a in accounts[:10]
            ],
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f"Plaid: {len(accounts)} account(s) refreshed.",
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
