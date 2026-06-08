"""GitHub — personal OAuth integration."""

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
class GitHubIntegration(IntegrationProvider):
    slug = "github"
    kind = "personal_oauth"
    display_name = "GitHub"
    category = "Code"
    description = "Track your repos, issues, and pull requests."
    docs_url = "https://docs.github.com/en/rest"
    icon = "github"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise PermissionError("personal integrations require an authenticated user")
        return await upsert_personal_integration(
            user=user, db=db, slug=self.slug, oauth_provider="github"
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        return await make_sync_via_dag("github_ingestor")(
            integration=integration, db=db
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="github"
        )
