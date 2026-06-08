"""Google Drive — personal OAuth, shares the user's existing Google grant.

Uses the access token already stored in oauth_tokens (granted at login).
If the token doesn't have drive.metadata.readonly (existing users from
before the scope widening), Google returns 403 — caught and surfaced as
"Re-auth required".
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx
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
class GoogleDriveIntegration(IntegrationProvider):
    slug = "google_drive"
    kind = "personal_oauth"
    display_name = "Google Drive"
    category = "Productivity"
    description = "Files, folders, search across your Drive."
    docs_url = "https://developers.google.com/drive"
    icon = "google-drive"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise PermissionError("personal integrations require an authenticated user")
        return await upsert_personal_integration(
            user=user, db=db, slug=self.slug, oauth_provider="google"
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        from sqlalchemy import select as _select

        from ...models.user import User as UserModel

        started = time.perf_counter()
        user = await db.scalar(
            _select(UserModel).where(UserModel.id == integration.user_id)
        )
        if user is None:
            raise IntegrationError("user_missing", "Owning user not found.")
        try:
            access_token, _account = await get_access_token(db, user, "google")
        except ProviderNotLinked:
            integration.status = "expired"
            integration.last_error = "Google OAuth account not linked."
            await db.commit()
            raise IntegrationError("not_linked", "Re-link Google to continue.")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://www.googleapis.com/drive/v3/files",
                    params={
                        "pageSize": 20,
                        "fields": "files(id,name,mimeType,modifiedTime)",
                    },
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code == 403:
                integration.status = "expired"
                integration.last_error = (
                    "Drive scope not granted. Log out + log back in to re-consent."
                )
                await db.commit()
                raise IntegrationError(
                    "scope_missing",
                    "Drive scope not on your token. Log out + log in again to grant it.",
                )
            resp.raise_for_status()
            files = (resp.json() or {}).get("files", [])
        except IntegrationError:
            raise
        except Exception as exc:  # noqa: BLE001
            integration.status = "error"
            integration.last_error = f"{type(exc).__name__}: {exc}"[:500]
            await db.commit()
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            "file_count": len(files),
            "files": [
                {"id": f.get("id"), "name": f.get("name"), "mime": f.get("mimeType")}
                for f in files[:10]
            ],
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=f"Drive: {len(files)} recent files cached.",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="google"
        )
