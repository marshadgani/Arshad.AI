"""Calendly — personal access token (read-only scheduled events).

The token is entered on the Integrations page and stored encrypted. The user's
Calendly URI is resolved once at connect time and kept in `Integration.config`
so the trip check can query scheduled events without an extra round trip.
"""

from __future__ import annotations

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
    require_api_key,
    store_api_key,
)
from ..registry import register

CALENDLY_API = "https://api.calendly.com"


async def probe_user(api_key: str, *, timeout: float = 10.0) -> dict[str, str]:
    """Validate the token and return {user_uri, user_timezone}.

    401/403 is an invalid token (IntegrationError); any other failure
    propagates as httpx.HTTPError (or ValueError for a non-JSON body) for the
    caller to classify.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{CALENDLY_API}/users/me",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code in (401, 403):
        raise IntegrationError("invalid_key", "Calendly rejected the access token.")
    resp.raise_for_status()
    payload = resp.json()
    resource = payload.get("resource") if isinstance(payload, dict) else None
    if not isinstance(resource, dict):
        resource = {}
    uri = resource.get("uri")
    if not isinstance(uri, str) or not uri:
        raise IntegrationError("probe_failed", "Calendly returned no user URI.")
    return {"user_uri": uri, "user_timezone": str(resource.get("timezone") or "")}


@register
class CalendlyIntegration(IntegrationProvider):
    slug = "calendly"
    kind = "personal_apikey"
    display_name = "Calendly"
    category = "Productivity"
    description = "Scheduled meetings for trip conflict checks (read-only)."
    docs_url = "https://developer.calendly.com/api-docs"
    icon = "calendar"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        api_key = require_api_key(payload)
        try:
            info = await probe_user(api_key)
        except (httpx.HTTPError, ValueError) as exc:
            raise IntegrationError(
                "probe_failed", f"Calendly unreachable: {type(exc).__name__}"
            ) from exc
        # The URI and timezone live in Integration.config only: they are not
        # secrets and a second copy in the credential's `extra` would be returned
        # by the status endpoint and could go stale.
        result = await store_api_key(
            db=db,
            slug=self.slug,
            api_key=api_key,
            extra={},
            scopes=["events:read"],
            user_id=user.id,
            kind="personal_apikey",
        )
        integration = await db.scalar(
            select(Integration).where(
                Integration.user_id == user.id, Integration.slug == self.slug
            )
        )
        if integration is None:
            raise IntegrationError(
                "connect_failed", "Calendly connected but the account was not saved."
            )
        integration.config = {**(integration.config or {}), **info}
        await db.commit()
        return result

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "Calendly token not stored.")
        try:
            info = await probe_user(decrypt(creds.encrypted_key), timeout=15.0)
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            if isinstance(exc, IntegrationError):
                if exc.code == "invalid_key":
                    integration.status = "expired"
                    await db.commit()
                raise
            raise IntegrationError("sync_failed", type(exc).__name__) from exc
        integration.config = {**(integration.config or {}), **info}
        return await mark_synced(
            integration=integration,
            db=db,
            summary="Calendly: account verified.",
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
