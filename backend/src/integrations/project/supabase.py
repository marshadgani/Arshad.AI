"""Supabase — project API-key integration.

API: https://api.supabase.com (management API).
Auth: Bearer <PAT>  — Personal Access Token from supabase.com/dashboard/account/tokens.

connect() probes /v1/projects to validate the token, stores it, and
records the project list in integration.config.
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
from ..registry import register
from ._shared import (
    mark_error,
    mark_synced,
    project_status,
    require_api_key,
    store_api_key,
)

_API = "https://api.supabase.com/v1"


async def _probe(api_key: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_API}/projects",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code in (401, 403):
        raise IntegrationError("invalid_key", "Supabase rejected the PAT.")
    resp.raise_for_status()
    body = resp.json() or []
    return {"project_count": len(body)}


@register
class SupabaseIntegration(IntegrationProvider):
    slug = "supabase"
    kind = "project_apikey"
    display_name = "Supabase"
    category = "Infrastructure"
    description = "Project list, table sizes, recent migrations."
    docs_url = "https://supabase.com/docs/reference/api"
    icon = "supabase"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        api_key = require_api_key(payload)
        try:
            probe = await _probe(api_key)
        except IntegrationError:
            raise
        except httpx.HTTPError as exc:
            raise IntegrationError(
                "probe_failed", f"Could not reach Supabase API: {type(exc).__name__}"
            )
        return await store_api_key(
            db=db,
            slug=self.slug,
            api_key=api_key,
            extra=probe,
            scopes=["projects:read"],
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "Supabase PAT not stored.")
        api_key = decrypt(creds.encrypted_key)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_API}/projects",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                projects = resp.json() or []
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            "project_count": len(projects),
            "projects": [
                {"ref": p.get("id"), "name": p.get("name"), "region": p.get("region")}
                for p in projects[:10]
            ],
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f"Fetched {len(projects)} Supabase projects.",
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
