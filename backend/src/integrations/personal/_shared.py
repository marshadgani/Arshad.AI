"""Login-backed personal integrations: connect, finalize, status.

Three OAuth flows co-exist in this codebase:

  (a) Phase G happy path — `upsert_personal_integration` below. The user
      already has an oauth_account for the underlying provider (Google or
      GitHub, from login) AND that account's token carries the scope this
      integration needs. connect() is then a pure DB operation: promote
      the existing grant into an Integration row. No browser redirect.

  (b) Attach flow — `attach_flow.start_attach_flow` (start) and
      `attach_callback.handle_attach_callback` (finish). Triggered when
      the account is missing entirely (never logged in with that provider)
      or the scope is missing (existing account predates a scope widening,
      or the user unchecked a box on Google's granular consent screen).
      The browser round-trips through the SAME registered
      `/api/v1/auth/{provider}/callback` used by login — GitHub allows
      only one callback URI per OAuth App — and that callback recognises
      the `att.` state prefix and routes to `attach_callback.py` instead
      of the login path. This is what replaces the old, broken
      `{FRONTEND_URL}/login?reason=missing_{provider}_scope` redirect,
      which App.tsx's LoginRoute guard silently discarded for an
      already-authenticated user (the bug this module used to have).

  (c) Phase H per-slug OAuthIntegrationProvider (`_oauth_base.py`) — a
      completely separate mechanism for providers that were never part of
      login (Spotify, Strava, Whoop, ...). Writes to `integrations` +
      `integration_oauth_tokens`, tables the chat tools never read. Not
      used by any of the six providers backed by this module.

What lives where (this module is deliberately thin):
  * `scope_policy.py` — which scope each slug needs, and the gap check.
  * `attach_flow.py`  — minting attach state + provider consent URL.
  * `dag_sync.py`     — the shared enqueue-a-DAG sync() implementation.
  * here              — deciding between (a) and (b), writing the
                        Integration row, and deriving StatusReport.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.attach_state import AttachError
from ...models.integration import Integration
from ...models.oauth_account import OAuthAccount
from ...models.user import User
from ..base import ConnectResult, StatusReport
from .attach_flow import start_attach_flow
from .dag_sync import make_sync_via_dag
from .scope_policy import REQUIRED_SCOPE_BY_SLUG, has_scope_gap

# Re-exported for the six provider modules, which import their whole
# personal-integration toolkit from this one facade.
__all__ = [
    "REQUIRED_SCOPE_BY_SLUG",
    "finalize_attached_integration",
    "make_sync_via_dag",
    "status_from_oauth_account",
    "upsert_personal_integration",
]


async def _load_usable_account(
    *, user_id: uuid.UUID, oauth_provider: str, slug: str, db: AsyncSession
) -> tuple[OAuthAccount | None, bool]:
    """Return (account, needs_attach) for one (user, provider, slug).

    The single place that answers "can this user's existing login grant
    serve this integration?" — both the connect path and the status path
    ask exactly that question and must never disagree about the answer.
    """
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user_id,
            OAuthAccount.provider == oauth_provider,
        )
    )
    if account is None:
        return None, True
    return account, await has_scope_gap(account, slug, db)


async def _ensure_connected_integration(
    *, user_id: uuid.UUID, slug: str, db: AsyncSession
) -> Integration:
    """Create the Integration row, or clear a previous failure on it."""
    integration = await db.scalar(
        select(Integration).where(
            Integration.user_id == user_id, Integration.slug == slug
        )
    )
    if integration is None:
        integration = Integration(
            user_id=user_id,
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
    return integration


async def upsert_personal_integration(
    *,
    user: User,
    db: AsyncSession,
    slug: str,
    oauth_provider: str,
) -> ConnectResult:
    """Connect path: promote an existing grant, or start the attach flow.

    Returns a ConnectResult carrying either an `integration_id` (done, no
    browser hop needed) or a `redirect_url` (send the user to the
    provider's consent screen).
    """
    _, needs_attach = await _load_usable_account(
        user_id=user.id, oauth_provider=oauth_provider, slug=slug, db=db
    )
    if needs_attach:
        return await start_attach_flow(
            user=user, slug=slug, oauth_provider=oauth_provider
        )

    integration = await _ensure_connected_integration(user_id=user.id, slug=slug, db=db)
    return ConnectResult(integration_id=str(integration.id), redirect_url=None)


async def finalize_attached_integration(
    *,
    user: User,
    db: AsyncSession,
    slug: str,
    oauth_provider: str,
) -> ConnectResult:
    """Callback path: same as `upsert_personal_integration`, except a
    remaining scope gap is a hard error rather than a second redirect.

    Called by `attach_callback.py` immediately after a fresh token
    exchange. If the scope is STILL missing at that point (Google's
    granular consent let the user uncheck the box), minting a second
    attach-state token and reporting success would just reproduce the
    original silent-bounce bug with new paint. Raising AttachError instead
    lets the callback report a real 'scope_not_granted' error back on the
    Integrations page.

    This is a separate function rather than a boolean flag on
    `upsert_personal_integration` because the two callers want opposite
    things from the same condition, and a call site reading
    `allow_attach_redirect=False` said nothing about why.
    """
    account, needs_attach = await _load_usable_account(
        user_id=user.id, oauth_provider=oauth_provider, slug=slug, db=db
    )
    if needs_attach:
        raise AttachError(
            "scope_not_granted" if account is not None else "account_not_attached",
            f"Required {oauth_provider} scope was not granted for '{slug}'.",
        )

    integration = await _ensure_connected_integration(user_id=user.id, slug=slug, db=db)
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

    account, needs_attach = await _load_usable_account(
        user_id=integration.user_id,
        oauth_provider=oauth_provider,
        slug=integration.slug,
        db=db,
    )

    extra: dict[str, Any] = {"oauth_provider": oauth_provider}
    if account is not None:
        extra["account_email"] = account.provider_email

    if account is None:
        resolved_status = "expired"
    elif needs_attach:
        resolved_status = "expired"
        extra["reason"] = "scope_missing"
    else:
        resolved_status = integration.status

    return StatusReport(
        status=resolved_status,  # type: ignore[arg-type]
        last_synced_at=(
            integration.last_synced_at.isoformat()
            if integration.last_synced_at
            else None
        ),
        last_error=integration.last_error,
        extra=extra,
    )
