"""Google Tasks — personal OAuth, shares the user's existing Google grant."""

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
class GoogleTasksIntegration(IntegrationProvider):
    slug = "google_tasks"
    kind = "personal_oauth"
    display_name = "Google Tasks"
    category = "Productivity"
    description = "Task lists and items synced from Google Tasks."
    docs_url = "https://developers.google.com/tasks"
    icon = "google-tasks"
    coming_soon = True
    coming_soon_reason = (
        "Connector ready but Google login scopes need to be widened to include "
        "tasks. Phase H will expand the consent set."
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
        return await make_sync_via_dag("tasks_ingestor")(integration=integration, db=db)

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="google"
        )
