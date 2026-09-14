"""Shared helpers for personal-OAuth integrations.

Phase G-MVP design choice: Google + GitHub OAuth already happens at login
(Phase C). Their tokens live in oauth_accounts/oauth_tokens. The personal
integrations here are *thin views* over that existing data — connecting
Google Calendar and Gmail does NOT trigger another OAuth flow because
the consent screen at login already covers all Google scopes.

For NEW providers added in Phase H (Notion, Slack, Linear), the OAuth flow
will require a separate /api/v1/integrations/oauth/{provider}/callback
endpoint to attach extra accounts to an already-authenticated user.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...models.oauth_account import OAuthAccount
from ...models.user import User
from ...services import dag_queue
from ..base import (
    ConnectResult,
    EnqueuedResult,
    IntegrationError,
    StatusReport,
    cannot_revoke,
)

# Why disconnecting any of these thin views revokes nothing upstream.
#
# This is the BR-005 constraint stated as user-facing copy. All five
# Google integrations and GitHub are views over ONE OAuth grant, the same
# one that backs the Arshad.AI login session: calling Google's or
# GitHub's revoke endpoint for "disconnect Google Calendar" would revoke
# Gmail, Drive, Tasks, YouTube and the user's login along with it. Their
# local per-integration rows are still deleted, and the shared
# `oauth_accounts` row is deliberately left untouched.
#
# Defined once here rather than repeated per provider: six copies of the
# same sentence is six chances for one of them to drift into a promise
# the code does not keep, which is the class of bug this whole
# declaration exists to close.
SHARED_GOOGLE_GRANT_REVOCATION = cannot_revoke(
    "Nothing is revoked with Google: this integration reuses the single "
    "Google sign-in grant shared with your other Google integrations and "
    "your Arshad.AI login, so revoking it would sign you out of all of "
    "them. Remove Arshad.AI at myaccount.google.com/permissions to revoke "
    "on Google's side."
)

SHARED_GITHUB_GRANT_REVOCATION = cannot_revoke(
    "Nothing is revoked with GitHub: this integration reuses the GitHub "
    "sign-in grant that also backs your Arshad.AI login, so revoking it "
    "would sign you out. Remove Arshad.AI under GitHub Settings → "
    "Applications to revoke on GitHub's side."
)


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


async def upsert_personal_integration(
    *, user: User, db: AsyncSession, slug: str, oauth_provider: str
) -> ConnectResult:
    """Phase G-MVP behavior: if the user already has an oauth_account for
    the underlying provider (Google or GitHub), promote it into an
    integration row. Otherwise tell the frontend to send the user back
    through the login flow with the right scopes."""
    existing_account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id,
            OAuthAccount.provider == oauth_provider,
        )
    )
    if existing_account is None:
        login_url = f"{_frontend_url()}/login?reason=missing_{oauth_provider}_scope"
        return ConnectResult(integration_id=None, redirect_url=login_url)

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
    DAG trigger row onto dag_trigger_queue.

    This is an adapter, not an implementation: the queueing rules
    (advisory lock, dedupe window, unique-index race handling) belong to
    services/dag_queue.py, which owns that table. All this function adds
    is the integrations layer's own vocabulary — an Integration as input,
    an EnqueuedResult with user-facing wording as output, and
    IntegrationError as the failure type the router already knows how to
    map to HTTP.

    Deliberately does NOT touch integration.last_synced_at/last_error —
    nothing has actually synced yet. Those fields are written once, and
    only once, by services/ingestion/runner.py after the queue worker (or
    Airflow) has genuinely processed the row. See CLAUDE.md FEAT-144.
    """

    async def _sync(*, integration: Integration, db: AsyncSession) -> EnqueuedResult:
        if integration.user_id is None:
            raise IntegrationError(
                "no_user", "Personal integrations require a user_id."
            )

        try:
            outcome = await dag_queue.enqueue_deduped(
                db,
                dag_id=dag_id,
                user_id=integration.user_id,
                payload={
                    "triggered_by": "integration_sync",
                    "slug": integration.slug,
                },
            )
        except dag_queue.EnqueueConflict as exc:
            raise IntegrationError(
                "sync_enqueue_conflict",
                f"{dag_id} sync could not be enqueued due to a "
                "concurrent request; please retry.",
            ) from exc

        summary = (
            f"{dag_id} is already queued — no duplicate sync started."
            if outcome.deduped
            else f"Queued {dag_id} for processing."
        )
        return EnqueuedResult(
            job_id=outcome.job_id,
            dag_id=outcome.dag_id,
            summary=summary,
            deduped=outcome.deduped,
        )

    return _sync
