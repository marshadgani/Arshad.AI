"""Render — project API-key integration.

API: https://api.render.com/v1/services
Auth: Bearer rnd_xxx (Render API key)

connect() probes /v1/services?limit=1 to validate the key, then stores it.
sync()    refreshes a small status snapshot in integration.config (first 10
services only; the rest are counted and flagged as truncated).
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
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
# Stored when a service's latest deploy could not be read (odd id, failed lookup,
# unreadable status). The trip check treats it as unknown, never as healthy.
DEPLOY_UNCHECKED = "unchecked"
_MAX_SERVICES = 10
_DEPLOY_CONCURRENCY = 3
_DEPLOY_TIMEOUT_SECONDS = 5.0


def _build_service_entries(
    kept: list[dict[str, Any]],
    deploy_results: list[Any],
) -> list[dict[str, Any]]:
    """Assemble the per-service snapshot rows from the raw API shapes.

    `deploy_results` is a parallel sequence aligned to services that have
    an `id` field; services without an id still appear in the output, their
    `latest_deploy_status` is DEPLOY_UNCHECKED. A failed lookup is stored the same
    way, so one flaky service does not discard the rest of the snapshot.
    """
    with_id = iter(deploy_results)
    entries: list[dict[str, Any]] = []
    for svc in kept:
        entries.append(
            {
                "id": svc.get("id"),
                "name": svc.get("name"),
                "type": svc.get("type"),
                "suspended": svc.get("suspended"),
                "latest_deploy_status": _deploy_value(next(with_id))
                if svc.get("id")
                else DEPLOY_UNCHECKED,
            }
        )
    return entries


def _deploy_value(result: Any) -> str | None:
    """A deploy lookup result as stored: a failed lookup becomes DEPLOY_UNCHECKED."""
    if isinstance(result, asyncio.CancelledError):
        raise result
    if isinstance(result, BaseException):
        return DEPLOY_UNCHECKED
    return result


# Render web services use "srv-" ids and cron jobs "crn-", each followed by
# alphanumerics. The id goes into a URL path, so anything else is refused rather
# than interpolated.
_SERVICE_ID = re.compile(r"(srv|crn)-[a-zA-Z0-9]+")


async def _latest_deploy_status(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    api_key: str,
    service_id: str,
) -> str | None:
    """Status of the newest deploy, None when the service has never deployed, or
    DEPLOY_UNCHECKED when the id or the status cannot be trusted."""
    if not _SERVICE_ID.fullmatch(service_id):
        return DEPLOY_UNCHECKED
    async with sem:
        resp = await asyncio.wait_for(
            client.get(
                f"{_RENDER_API}/services/{service_id}/deploys?limit=1",
                headers={"Authorization": f"Bearer {api_key}"},
            ),
            timeout=_DEPLOY_TIMEOUT_SECONDS,
        )
    resp.raise_for_status()
    deploys = resp.json() or []
    if not deploys:
        return None
    status = (deploys[0].get("deploy") or {}).get("status")
    return status if isinstance(status, str) and status else DEPLOY_UNCHECKED


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
                kept = [s.get("service") or {} for s in services[:_MAX_SERVICES]]
                sem = asyncio.Semaphore(_DEPLOY_CONCURRENCY)
                deploy_results = await asyncio.gather(
                    *(
                        _latest_deploy_status(client, sem, api_key, str(svc["id"]))
                        for svc in kept
                        if svc.get("id")
                    ),
                    return_exceptions=True,
                )
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", type(exc).__name__)
        if any(isinstance(r, asyncio.CancelledError) for r in deploy_results):
            raise asyncio.CancelledError
        entries = _build_service_entries(kept, deploy_results)
        integration.config = {
            "service_count": len(services),
            "services_truncated": len(services) > _MAX_SERVICES,
            "services": entries,
            "synced_at": datetime.now(timezone.utc).isoformat(),
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
