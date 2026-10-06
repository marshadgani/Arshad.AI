"""Shared helpers for personal-OAuth integrations.

Phase G-MVP design choice: Google + GitHub OAuth already happens at login
(Phase C). Their tokens live in oauth_accounts/oauth_tokens. The personal
integrations here are *thin views* over that existing data — connecting
Google Calendar and Gmail does NOT trigger another OAuth flow because
the consent screen at login already covers all Google scopes.

When the signed-in user has no oauth_account for the provider (logged in with
a different one), _attach.py runs an authenticated attach flow instead.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...models.oauth_account import OAuthAccount
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    StatusReport,
    SyncResult,
)


async def upsert_personal_integration(
    *, user: User, db: AsyncSession, slug: str, oauth_provider: str
) -> ConnectResult:
    """Phase G-MVP behavior: if the user already has an oauth_account for
    the underlying provider (Google or GitHub), promote it into an
    integration row. Otherwise signal needs_oauth_attach so the caller
    starts the authenticated attach flow (see _attach.py)."""
    existing_account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id,
            OAuthAccount.provider == oauth_provider,
        )
    )
    if existing_account is None:
        return ConnectResult(needs_oauth_attach=True)

    integration = await db.scalar(
        select(Integration).where(
            Integration.user_id == user.id, Integration.slug == slug
        )
    )
    if integration is None:
        integration = Integration(
            user_id=user.id,
            slug=slug,
            kind="personal_oauth",
            status="connected",
            config={},
        )
        db.add(integration)
        await db.commit()
        await db.refresh(integration)
    else:
        integration.status = "connected"
        integration.last_error = None
        await db.commit()

    return ConnectResult(integration_id=str(integration.id), redirect_url=None)


async def status_from_oauth_account(
    *,
    integration: Integration,
    db: AsyncSession,
    oauth_provider: str,
) -> StatusReport:
    if integration.status == "disconnected":
        return StatusReport(
            status="disconnected",
            last_synced_at=None,
            last_error=None,
            extra={"oauth_provider": oauth_provider},
        )
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == integration.user_id,
            OAuthAccount.provider == oauth_provider,
        )
    )
    extra: dict[str, Any] = {"oauth_provider": oauth_provider}
    if account is not None:
        extra["account_email"] = account.provider_email
    return StatusReport(
        status=integration.status if account else "expired",  # type: ignore[arg-type]
        last_synced_at=(
            integration.last_synced_at.isoformat()
            if integration.last_synced_at
            else None
        ),
        last_error=integration.last_error,
        extra=extra,
    )


def make_sync_via_dag(dag_id: str):
    """Returns an async sync() implementation that enqueues a Phase F
    DAG trigger row. Reuses the existing dag_trigger_queue table."""

    async def _sync(*, integration: Integration, db: AsyncSession) -> SyncResult:
        from ...models.dag_trigger import DagTriggerQueue  # local to avoid cycles

        if integration.user_id is None:
            raise IntegrationError(
                "no_user", "Personal integrations require a user_id."
            )
        started = time.perf_counter()
        row = DagTriggerQueue(
            dag_id=dag_id,
            user_id=integration.user_id,
            payload={"triggered_by": "integration_sync", "slug": integration.slug},
        )
        db.add(row)
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        await db.commit()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return SyncResult(
            rows_written=0,
            summary=f"Enqueued {dag_id} for processing.",
            duration_ms=elapsed_ms,
        )

    return _sync
