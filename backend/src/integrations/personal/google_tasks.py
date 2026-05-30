"""Google Tasks — personal OAuth, shares the user's existing Google grant."""

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
class GoogleTasksIntegration(IntegrationProvider):
    slug = "google_tasks"
    kind = "personal_oauth"
    display_name = "Google Tasks"
    category = "Productivity"
    description = "Task lists and items synced from Google Tasks."
    docs_url = "https://developers.google.com/tasks"
    icon = "google-tasks"

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
                    "https://tasks.googleapis.com/tasks/v1/users/@me/lists",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code == 403:
                integration.status = "expired"
                integration.last_error = (
                    "Tasks scope not granted. Log out + log back in to re-consent."
                )
                await db.commit()
                raise IntegrationError(
                    "scope_missing",
                    "Tasks scope not on your token. Re-login required.",
                )
            resp.raise_for_status()
            lists = (resp.json() or {}).get("items", [])
        except IntegrationError:
            raise
        except Exception as exc:  # noqa: BLE001
            integration.status = "error"
            integration.last_error = f"{type(exc).__name__}: {exc}"[:500]
            await db.commit()
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            "list_count": len(lists),
            "lists": [{"id": l.get("id"), "title": l.get("title")} for l in lists],
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=f"Google Tasks: {len(lists)} lists cached.",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="google"
        )
