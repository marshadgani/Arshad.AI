"""Google Calendar — personal OAuth integration.

Reuses the user's existing Google OAuth grant from Phase C login. No separate
consent flow because Calendar scope is already in the login scope set.
Sync enqueues the Phase F calendar_ingestor DAG.
"""

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
class GoogleCalendarIntegration(IntegrationProvider):
    slug = "google_calendar"
    kind = "personal_oauth"
    display_name = "Google Calendar"
    category = "Calendar"
    description = "Sync your Google Calendar events into Arshad.AI."
    docs_url = "https://developers.google.com/calendar"
    icon = "google-calendar"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise PermissionError("personal integrations require an authenticated user")
        return await upsert_personal_integration(
            user=user, db=db, slug=self.slug, oauth_provider="google"
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        return await make_sync_via_dag("calendar_ingestor")(
            integration=integration, db=db
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="google"
        )
