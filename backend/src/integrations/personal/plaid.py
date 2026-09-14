"""Plaid (US banking) — Link SDK token exchange.

Plaid uses a 2-step token flow:
  1. Frontend calls /link/token/create to get a `link_token`
  2. User completes Plaid Link UI → frontend gets a `public_token`
  3. Backend exchanges public_token → access_token (long-lived)
  4. Backend calls /accounts/get + /transactions/get with access_token

This provider's connect() accepts EITHER of two payload shapes:
  - {public_token: "..."} — exchanged upstream for an access_token via
    Plaid's /item/public_token/exchange. That token is trusted upstream
    output and is not format-validated client-side.
  - {api_key: "access-..."} — the user pastes a Plaid access_token
    directly (e.g. from Plaid's quickstart sandbox tool). This path is
    format-validated locally (_validate_pasted_access_token) before
    storage: no network probe is made, to avoid consuming Plaid quota.

Phase J will add a proper Link button to the Integrations UI that fetches
a link_token from /api/v1/integrations/plaid/link-token, runs Plaid Link,
and POSTs the resulting public_token to /connect — turning this from a
paste-public-token flow into a 1-click flow.
"""

from __future__ import annotations

import logging
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
    UpstreamRevocationResult,
)
from ..project._shared import (
    mark_error,
    mark_synced,
    project_status,
    store_api_key,
)
from ..registry import register

_log = logging.getLogger(__name__)


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


def _validate_pasted_access_token(raw: Any) -> str:
    """Format/sanity-check a user-pasted Plaid access_token before storage.

    Pure — no DB, no network, no logging of the token. Only the
    direct-paste branch of connect() calls this; the public_token exchange
    branch gets its access_token from Plaid's own response and must not be
    subjected to these client-side gates.

    Returns the stripped token on success; raises IntegrationError
    otherwise. No raised message ever contains the token itself.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise IntegrationError(
            "invalid_api_key",
            "api_key must be a non-empty text value containing a Plaid access token.",
        )
    token = raw.strip()

    if not token.startswith("access-"):
        raise IntegrationError(
            "invalid_api_key",
            "Plaid access tokens start with 'access-'. A 'public-...' token "
            "from Plaid Link must be sent as {public_token}, not {api_key}.",
        )

    if not (20 <= len(token) <= 500):
        raise IntegrationError(
            "invalid_api_key",
            "Plaid access token length is outside the expected range (20-500 characters).",
        )

    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token):
        raise IntegrationError(
            "invalid_api_key",
            "Plaid access token must not contain whitespace or control characters.",
        )

    # The "access-<env>-<uuid>" shape is an OBSERVED Plaid convention, not a
    # contractual one, and Plaid has sunset environments before (e.g.
    # "development"). An unrecognised segment is accepted rather than
    # rejected so this check never locks out a legitimately-held token —
    # do not tighten this to reject unknown segments.
    parts = token.split("-")
    segment = parts[1] if len(parts) >= 2 else ""
    env = _plaid_env()
    if segment in ("sandbox", "development", "production") and segment != env:
        raise IntegrationError(
            "invalid_api_key",
            f"This looks like a '{segment}' token but the backend is configured "
            f"for PLAID_ENV='{env}'. Use a token minted for the configured environment.",
        )

    return token


@register
class PlaidIntegration(IntegrationProvider):
    slug = "plaid"
    kind = "personal_apikey"  # treated as per-user key (the access_token)
    display_name = "Plaid (US Banking)"
    category = "Finance"
    description = "US bank accounts, balances, transactions via Plaid Link."
    docs_url = "https://plaid.com/docs/"
    icon = "plaid"
    # FEAT-145: Plaid is the highest-value credential in this codebase
    # (financial data) and has a real revoke endpoint (item/remove), so
    # this is worth a real upstream revoke rather than local-scrub-only.
    revocation_kind = "revokes"

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
            # Direct paste path — usually a sandbox access_token starting
            # "access-sandbox-". No probe call (would consume Plaid quota);
            # format/env checked locally by _validate_pasted_access_token
            # instead, so a malformed or wrong-env paste is rejected before
            # it is ever encrypted to storage.
            token = _validate_pasted_access_token(api_key)
            return await store_api_key(
                db=db,
                slug=self.slug,
                api_key=token,
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

    async def _prepare_revocation(
        self, *, integration: Integration, db: AsyncSession
    ) -> dict[str, str] | None:
        """Decrypt the stored access_token and gather the Plaid client
        credentials while the read transaction is still open. Returns None
        (→ disconnect() reports 'unsupported') when there's nothing to
        revoke or PLAID_CLIENT_ID/PLAID_SECRET aren't configured — the
        local credential is still scrubbed either way.
        """
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            return None
        try:
            access_token = decrypt(creds.encrypted_key)
        except Exception:  # noqa: BLE001 — corrupt ciphertext must not block disconnect
            _log.warning(
                "Could not decrypt stored Plaid access_token (integration_id=%s) "
                "during disconnect — skipping upstream revoke.",
                integration.id,
                exc_info=True,
            )
            return None
        try:
            plaid_creds = _plaid_creds()
        except IntegrationError:
            return None
        return {"access_token": access_token, **plaid_creds}

    async def _revoke_upstream(
        self, *, payload: dict[str, str]
    ) -> UpstreamRevocationResult:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{_plaid_base_url()}/item/remove", json=payload
                )
        except httpx.HTTPError:
            _log.warning("Plaid item/remove request failed", exc_info=True)
            return "failed"
        if 200 <= resp.status_code < 300:
            return "revoked"
        _log.warning(
            "Plaid item/remove returned %s: %s", resp.status_code, resp.text[:200]
        )
        return "failed"
