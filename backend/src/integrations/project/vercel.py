"""Vercel — project API-key integration.

API: https://api.vercel.com
Auth: Bearer <token>
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

_VERCEL_API = "https://api.vercel.com"


async def _probe(api_key: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_VERCEL_API}/v2/user",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code in (401, 403):
        raise IntegrationError("invalid_key", "Vercel rejected the token.")
    resp.raise_for_status()
    body = resp.json() or {}
    return {"username": body.get("user", {}).get("username")}


@register
class VercelIntegration(IntegrationProvider):
    slug = "vercel"
    kind = "project_apikey"
    display_name = "Vercel"
    category = "Infrastructure"
    description = "Project list, deploy history, build status."
    docs_url = "https://vercel.com/docs/rest-api"
    icon = "vercel"

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
                "probe_failed", f"Could not reach Vercel API: {type(exc).__name__}"
            )
        return await store_api_key(
            db=db,
            slug=self.slug,
            api_key=api_key,
            extra=probe,
            scopes=["projects:read", "deployments:read"],
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "Vercel token not stored.")
        api_key = decrypt(creds.encrypted_key)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_VERCEL_API}/v9/projects?limit=20",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                projects = (resp.json() or {}).get("projects", [])
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            "project_count": len(projects),
            "projects": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "framework": p.get("framework"),
                }
                for p in projects[:10]
            ],
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f"Fetched {len(projects)} Vercel projects.",
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
