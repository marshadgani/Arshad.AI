"""YouTube — personal OAuth, shares the user's existing Google grant.

Reads subscriptions and recent activity using youtube.readonly scope.
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
from ...tools.base import ProviderNotLinked
from ...tools.token_service import get_access_token
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from ..registry import register
from ._shared import (
    status_from_oauth_account,
    upsert_personal_integration,
)


@register
class YouTubeIntegration(IntegrationProvider):
    slug = "youtube"
    kind = "personal_oauth"
    display_name = "YouTube"
    category = "Lifestyle"
    description = "Subscriptions, channel info, recent uploads."
    docs_url = "https://developers.google.com/youtube/v3"
    icon = "youtube"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise PermissionError("personal integrations require an authenticated user")
        return await upsert_personal_integration(
            user=user, db=db, slug=self.slug, oauth_provider="google"
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        user = await db.scalar(select(User).where(User.id == integration.user_id))
        if user is None:
            raise IntegrationError("user_missing", "Owning user not found.")
        try:
            access_token, _ = await get_access_token(db, user, "google")
        except ProviderNotLinked:
            integration.status = "expired"
            integration.last_error = "Google OAuth account not linked."
            await db.commit()
            raise IntegrationError("not_linked", "Re-link Google to continue.")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/subscriptions",
                    params={"part": "snippet", "mine": "true", "maxResults": 20},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code == 403:
                integration.status = "expired"
                integration.last_error = (
                    "YouTube scope not granted. Log out + log back in to re-consent."
                )
                await db.commit()
                raise IntegrationError(
                    "scope_missing",
                    "YouTube scope not on your token. Re-login required.",
                )
            resp.raise_for_status()
            subs = (resp.json() or {}).get("items", [])
        except IntegrationError:
            raise
        except Exception as exc:  # noqa: BLE001
            integration.status = "error"
            integration.last_error = f"{type(exc).__name__}: {exc}"[:500]
            await db.commit()
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            "subscription_count": len(subs),
            "subscriptions": [
                {
                    "title": (s.get("snippet") or {}).get("title"),
                    "channel_id": (
                        (s.get("snippet") or {}).get("resourceId") or {}
                    ).get("channelId"),
                }
                for s in subs[:10]
            ],
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=f"YouTube: {len(subs)} subscriptions cached.",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="google"
        )
