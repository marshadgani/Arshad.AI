"""Gmail — personal OAuth integration. Shares Google OAuth grant with Calendar."""

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
class GmailIntegration(IntegrationProvider):
    slug = "gmail"
    kind = "personal_oauth"
    display_name = "Gmail"
    category = "Communication"
    description = "Search threads, draft replies, and label your Gmail."
    docs_url = "https://developers.google.com/gmail/api"
    icon = "gmail"
    sync_dag_id = "email_ingestor"
    # FEAT-145: no integration_oauth_tokens row — the credential is the
    # login-time Google grant in oauth_accounts/oauth_tokens, shared with
    # Calendar/Drive/Tasks/YouTube and the user's own session. Revoking it
    # here would break all of those, so disconnect() only stops the sync
    # (see integrations/DECISION.md §1).
    revocation_kind = "no_credential"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise PermissionError("personal integrations require an authenticated user")
        return await upsert_personal_integration(
            user=user, db=db, slug=self.slug, oauth_provider="google"
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        return await make_sync_via_dag(self.sync_dag_id)(integration=integration, db=db)

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await status_from_oauth_account(
            integration=integration, db=db, oauth_provider="google"
        )
