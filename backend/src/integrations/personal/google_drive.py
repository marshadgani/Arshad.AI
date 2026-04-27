"""Google Drive — personal OAuth, shares the user's existing Google grant."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...models.user import User
from ..base import ConnectResult, IntegrationProvider, StatusReport, SyncResult
from ..registry import register
from ._shared import (
    make_sync_via_dag,
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
    coming_soon = True
    coming_soon_reason = (
        "Connector ready but Google login scopes need to be widened to include "
        "drive.metadata.readonly. Phase H will expand the consent set."
    )

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise PermissionError("personal integrations require an authenticated user")
        return await upsert_personal_integration(
            user=user, db=db, slug=self.slug, oauth_provider="google"
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        # No drive_ingestor DAG yet — Phase H will add one.
        return await make_sync_via_dag("drive_ingestor")(integration=integration, db=db)

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="google"
        )
