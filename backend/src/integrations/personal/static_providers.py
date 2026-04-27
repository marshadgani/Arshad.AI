"""Static (no-credentials) personal integrations.

Some providers don't require any credentials — Hacker News, Open-Meteo
(weather), generic RSS. The user just toggles them on, optionally provides
config (lat/lon for weather, feed URLs for RSS). connect() creates the
integration row immediately without any key/token storage.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from ..registry import register


async def _upsert_static_integration(
    *,
    user: User,
    db: AsyncSession,
    slug: str,
    config: dict[str, Any] | None = None,
) -> ConnectResult:
    integration = await db.scalar(
        select(Integration).where(
            Integration.user_id == user.id, Integration.slug == slug
        )
    )
    if integration is None:
        integration = Integration(
            user_id=user.id,
            slug=slug,
            kind="static",
            status="connected",
            config=config or {},
        )
        db.add(integration)
        await db.commit()
        await db.refresh(integration)
    else:
        integration.status = "connected"
        integration.last_error = None
        if config:
            integration.config = {**(integration.config or {}), **config}
        await db.commit()
    return ConnectResult(integration_id=str(integration.id), redirect_url=None)


# ── Hacker News ──────────────────────────────────────────────────────────


@register
class HackerNewsIntegration(IntegrationProvider):
    slug = "hacker_news"
    kind = "static"
    display_name = "Hacker News"
    category = "Lifestyle"
    description = "Top stories. No auth required — just toggle on."
    docs_url = "https://github.com/HackerNews/API"
    icon = "hackernews"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        return await _upsert_static_integration(user=user, db=db, slug=self.slug)

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://hacker-news.firebaseio.com/v0/topstories.json"
                )
                resp.raise_for_status()
                ids = (resp.json() or [])[:10]
        except Exception as exc:  # noqa: BLE001
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {"top_story_count": len(ids), "top_story_ids": ids}
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=f"Hacker News: top {len(ids)} stories cached.",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return StatusReport(
            status=integration.status,  # type: ignore[arg-type]
            last_synced_at=(
                integration.last_synced_at.isoformat()
                if integration.last_synced_at
                else None
            ),
            last_error=integration.last_error,
            extra=dict(integration.config or {}),
        )


# ── Open-Meteo (weather, no key) ─────────────────────────────────────────


@register
class OpenMeteoIntegration(IntegrationProvider):
    slug = "open_meteo"
    kind = "static"
    display_name = "Open-Meteo"
    category = "Lifestyle"
    description = "Free weather API — no key. Provide lat/lon in config."
    docs_url = "https://open-meteo.com/en/docs"
    icon = "weather"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        # Optional config: lat/lon. Default to London.
        lat = (payload or {}).get("latitude", 51.5074)
        lon = (payload or {}).get("longitude", -0.1278)
        return await _upsert_static_integration(
            user=user,
            db=db,
            slug=self.slug,
            config={"latitude": lat, "longitude": lon},
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        cfg = integration.config or {}
        lat, lon = cfg.get("latitude", 51.5074), cfg.get("longitude", -0.1278)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,weather_code",
                    },
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        current = body.get("current", {})
        integration.config = {
            **cfg,
            "last_temperature_c": current.get("temperature_2m"),
            "last_weather_code": current.get("weather_code"),
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=f"Open-Meteo: {lat},{lon} → {current.get('temperature_2m')}°C",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return StatusReport(
            status=integration.status,  # type: ignore[arg-type]
            last_synced_at=(
                integration.last_synced_at.isoformat()
                if integration.last_synced_at
                else None
            ),
            last_error=integration.last_error,
            extra=dict(integration.config or {}),
        )
