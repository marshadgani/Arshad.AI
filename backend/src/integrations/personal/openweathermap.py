"""OpenWeatherMap — query-param auth, doesn't fit the bulk factory."""

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

_BASE = "https://api.openweathermap.org/data/2.5"


@register
class OpenWeatherMapIntegration(IntegrationProvider):
    slug = "openweathermap"
    kind = "personal_apikey"
    display_name = "OpenWeatherMap"
    category = "Lifestyle"
    description = "Current weather and 5-day forecasts via API key."
    docs_url = "https://openweathermap.org/api"
    icon = "weather"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        api_key = require_api_key(payload)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_BASE}/weather",
                    params={"q": "London", "appid": api_key},
                )
            if resp.status_code in (401, 403):
                raise IntegrationError(
                    "invalid_key",
                    "OpenWeatherMap rejected the key (free keys take ~10 min to activate).",
                )
            resp.raise_for_status()
        except IntegrationError:
            raise
        except httpx.HTTPError as exc:
            raise IntegrationError(
                "probe_failed", f"OpenWeatherMap unreachable: {type(exc).__name__}"
            )
        return await store_api_key(
            db=db,
            slug=self.slug,
            api_key=api_key,
            extra={"verified_with_city": "London"},
            scopes=["weather:read"],
            user_id=user.id,
            kind="personal_apikey",
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "OpenWeatherMap key not stored.")
        api_key = decrypt(creds.encrypted_key)
        # Sync grabs current weather for a configured city (default: London).
        city = (integration.config or {}).get("city", "London")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_BASE}/weather", params={"q": city, "appid": api_key}
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            "city": city,
            "last_temperature_kelvin": (body.get("main") or {}).get("temp"),
            "last_conditions": [w.get("main") for w in (body.get("weather") or [])],
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f"OpenWeatherMap: {city} weather refreshed.",
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
