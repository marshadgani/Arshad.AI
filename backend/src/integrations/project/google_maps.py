"""Google Maps Places — project_apikey integration.

Uses a Google Cloud Platform API key (different from OAuth client_id).
Probe: a tiny Places API text-search call to verify the key works.
Sync: refreshes a single 'home' place lookup if config.home_query is set.

Per-feature billing applies on the user's GCP account.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
    cannot_revoke,
    safe_detail,
)
from ..registry import register
from ._shared import (
    load_api_key,
    mark_error,
    mark_synced,
    project_status,
    require_api_key,
    store_api_key,
)

_PLACES_TEXT_SEARCH = "https://places.googleapis.com/v1/places:searchText"


@register
class GoogleMapsIntegration(IntegrationProvider):
    slug = "google_maps"
    kind = "project_apikey"
    display_name = "Google Maps Places"
    category = "Lifestyle"
    description = "Place lookups, directions, geocoding via Google Maps Platform."
    docs_url = "https://developers.google.com/maps/documentation/places/web-service"
    icon = "google-maps"
    upstream_revocation = cannot_revoke(
        "Google Cloud has no API for deleting an API key, so the key itself is "
        "not revoked — only Arshad.AI's encrypted copy is deleted. Delete "
        "the key at console.cloud.google.com → APIs & Services → "
        "Credentials to revoke it fully."
    )

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        api_key = require_api_key(payload)
        # Probe: search for a known place
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    _PLACES_TEXT_SEARCH,
                    json={"textQuery": "Googleplex Mountain View"},
                    headers={
                        "X-Goog-Api-Key": api_key,
                        "X-Goog-FieldMask": "places.displayName",
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code in (401, 403):
                raise IntegrationError(
                    "invalid_key",
                    "Google rejected the key. Check Places API is enabled in the GCP console.",
                )
            resp.raise_for_status()
        except IntegrationError:
            raise
        except httpx.HTTPError as exc:
            raise IntegrationError(
                "probe_failed", f"Google Maps unreachable: {type(exc).__name__}"
            )
        return await store_api_key(
            db=db,
            slug=self.slug,
            api_key=api_key,
            extra={"places_api_verified": True},
            scopes=["places.textsearch"],
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        api_key = await load_api_key(
            integration=integration, db=db, display_name=self.display_name
        )
        query = (integration.config or {}).get("home_query", "Googleplex Mountain View")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _PLACES_TEXT_SEARCH,
                    json={"textQuery": query},
                    headers={
                        "X-Goog-Api-Key": api_key,
                        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", safe_detail(exc)) from exc
        places = body.get("places", [])
        integration.config = {
            **(integration.config or {}),
            "last_query": query,
            "last_result_count": len(places),
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f'Google Maps: "{query}" returned {len(places)} place(s).',
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
