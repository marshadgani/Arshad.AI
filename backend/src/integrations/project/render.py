"""Render — project API-key integration.

API: https://api.render.com/v1/services
Auth: Bearer rnd_xxx (Render API key)

connect() probes /v1/services?limit=1 to validate the key, then stores it.
sync()    refreshes a small status snapshot in integration.config.
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

_RENDER_API = "https://api.render.com/v1"


async def _probe(api_key: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_RENDER_API}/services?limit=1",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code == 401:
        raise IntegrationError("invalid_key", "Render rejected the API key (401).")
    resp.raise_for_status()
    return {"sample_count": len(resp.json() or [])}


@register
class RenderIntegration(IntegrationProvider):
    slug = "render"
    kind = "project_apikey"
    display_name = "Render"
    category = "Infrastructure"
    description = "Read service status, deploys, and quotas from Render."
    docs_url = "https://api-docs.render.com/reference/introduction"
    icon = "render"

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
                "probe_failed", f"Could not reach Render API: {type(exc).__name__}"
            )
        return await store_api_key(
            db=db,
            slug=self.slug,
            api_key=api_key,
            extra=probe,
            scopes=["services:read"],
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "Render API key not stored.")
        api_key = decrypt(creds.encrypted_key)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_RENDER_API}/services?limit=20",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                services = resp.json() or []
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            "service_count": len(services),
            "services": [
                {
                    "id": s.get("service", {}).get("id"),
                    "name": s.get("service", {}).get("name"),
                    "type": s.get("service", {}).get("type"),
                }
                for s in services[:10]
            ],
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f"Fetched {len(services)} Render services.",
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
