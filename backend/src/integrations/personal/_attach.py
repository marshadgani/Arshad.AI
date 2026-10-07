"""Authenticated "attach a provider to the signed-in user" OAuth flow.

Used by the six personal providers (GitHub, Gmail, Google Calendar/Drive/
Tasks/YouTube) when the signed-in user has no oauth_account for the
provider (e.g. they logged in with Google and now connect GitHub), or when
their stored Google login was revoked and needs a fresh consent.

Flow (identity is NEVER taken from a URL-borne value alone):
  1. POST /{slug}/connect (JWT)  -> state stored in Redis bound to user_id.
  2. Provider -> GET attach callback (anonymous browser nav): state consumed
     once; the code is encrypted into a short-lived pending record that
     carries the initiating user_id. Nothing is linked here.
  3. Frontend -> POST /oauth-complete (JWT): the session user must equal the
     pending record's user_id; only then is the code exchanged and tokens
     stored against that user_id.

Pending-record management (store/peek/consume/decrypt) lives in _pending.py.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import TokenDecryptError, encrypt
from ...auth.providers.base import (
    OAuthError,
    OAuthProvider,
    OAuthTokenBundle,
    OAuthUserInfo,
)
from ...auth.providers.github import GitHubOAuthProvider
from ...auth.providers.google import GoogleOAuthProvider
from ...models.oauth_account import OAuthAccount
from ...models.oauth_token import OAuthToken
from ...models.user import User
from ...tools.base import ProviderReauthRequired
from ...tools.token_service import refresh_google_token
from ..base import ConnectResult, IntegrationError
from ._oauth_base import store_oauth_state
from ._pending import (
    consume_attach_pending,
    decrypt_pending_code,
    peek_attach_pending,
    store_attach_pending,  # noqa: F401 — re-exported for routers
)
from ._shared import upsert_personal_integration

_log = logging.getLogger(__name__)

ATTACH_PROVIDERS = frozenset({"github", "google"})


# ── Provider factory ──────────────────────────────────────────────────────


def attach_redirect_uri(oauth_provider: str) -> str:
    """Redirect URI for the attach flow; the same value goes into the authorize
    URL and the token exchange, and must be registered with the provider.

    GitHub OAuth Apps accept a redirect_uri only at or below the single
    callback URL registered for the app, so GitHub's attach callback lives
    under the login callback path and needs no extra console change.
    """
    backend = os.getenv("BACKEND_URL", "").rstrip("/")
    if not backend:
        raise IntegrationError(
            "backend_url_not_configured", "OAuth redirect is not configured."
        )
    if oauth_provider == "github":
        return f"{backend}/api/v1/auth/github/callback/attach"
    return f"{backend}/api/v1/integrations/personal/attach/{oauth_provider}/callback"


def _get_provider_for_attach(oauth_provider: str) -> OAuthProvider:
    try:
        if oauth_provider == "github":
            provider = GitHubOAuthProvider()
        elif oauth_provider == "google":
            provider = GoogleOAuthProvider()
        else:
            raise IntegrationError(
                "unsupported_oauth_provider",
                f"Unsupported provider '{oauth_provider}'.",
            )
    except RuntimeError as exc:
        _log.error("attach provider %s is not configured", oauth_provider)
        raise IntegrationError(
            "provider_not_configured", "This provider is not configured on the server."
        ) from exc
    # Same redirect_uri must be used for the authorize URL and the token
    # exchange; both go through this factory.
    provider.redirect_uri = attach_redirect_uri(oauth_provider)
    return provider


# ── Flow orchestration ────────────────────────────────────────────────────


async def start_personal_oauth_attach(
    *, user_id: str, slug: str, oauth_provider: str
) -> ConnectResult:
    """Step 1: build the provider authorize URL with a server-side state."""
    provider = _get_provider_for_attach(oauth_provider)
    state = await store_oauth_state(
        user_id=user_id, slug=slug, ctx={"oauth_provider": oauth_provider}
    )
    return ConnectResult(redirect_url=provider.authorization_url(state))


async def connect_personal_oauth(
    *, user: User, db: AsyncSession, slug: str, oauth_provider: str
) -> ConnectResult:
    """Connect a personal OAuth provider for the signed-in user.

    The attach flow starts when the user has no account for the provider, or
    when their Google login was revoked (see ``_google_login_revoked``).
    Otherwise the existing account is promoted into an integration row.
    """
    # Read before any rollback: rolling back expires ``user``, and a lazy
    # refresh on an AsyncSession raises MissingGreenlet.
    user_id = str(user.id)
    needs_attach = oauth_provider == "google" and await _google_login_revoked(
        user=user, db=db
    )
    if not needs_attach:
        result = await upsert_personal_integration(
            user=user, db=db, slug=slug, oauth_provider=oauth_provider
        )
        if not result.needs_oauth_attach:
            return result
    return await start_personal_oauth_attach(
        user_id=user_id, slug=slug, oauth_provider=oauth_provider
    )


async def _google_login_revoked(*, user: User, db: AsyncSession) -> bool:
    """True when the user's stored Google refresh token no longer works.

    Without this, Connect on an existing account only flips the card to
    Connected and never sends the user to Google, so a revoked login stays
    broken forever. The attach flow's account-update branch then stores the
    fresh tokens on the same account.

    Fails open: any other error (Google outage, timeout, missing config)
    returns False so Connect keeps its previous behaviour instead of
    returning a 500. A still-valid access token skips the probe, which also
    avoids a row lock and a token write on every Connect click.
    """
    row = (
        await db.execute(
            select(OAuthAccount.id, OAuthToken.token_expires_at)
            .outerjoin(OAuthToken, OAuthToken.oauth_account_id == OAuthAccount.id)
            .where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "google")
        )
    ).first()
    if row is None:
        return False
    account_id, expires_at = row
    if expires_at is not None and expires_at > datetime.now(timezone.utc):
        return False
    try:
        await refresh_google_token(db, account_id)
    except ProviderReauthRequired:
        await db.rollback()
        return True
    except (
        httpx.HTTPError,
        RuntimeError,
        KeyError,
        ValueError,
        TokenDecryptError,
        SQLAlchemyError,
    ) as exc:
        await db.rollback()
        # The caller goes on to read ``user`` (upsert_personal_integration),
        # and the rollback just expired it.
        await db.refresh(user)
        _log.warning("google login probe failed: %s", type(exc).__name__)
        return False
    return False


# ── Account and token persistence ────────────────────────────────────────


async def _attach_account_to_user(
    *,
    user_id: str,
    oauth_provider: str,
    info: OAuthUserInfo,
    bundle: OAuthTokenBundle,
    db: AsyncSession,
) -> None:
    """Store the provider account and encrypted tokens for user_id only.

    Raises IntegrationError("account_already_linked") if the provider account
    belongs to another user or the user already has a different one for this
    provider.
    """
    uid = uuid.UUID(user_id)
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == oauth_provider,
            OAuthAccount.provider_user_id == info.provider_user_id,
        )
    )
    if account is not None and account.user_id != uid:
        raise IntegrationError(
            "account_already_linked",
            f"This {oauth_provider} account is already linked to a different user.",
        )
    is_new_account = account is None
    if account is None:
        # No unique (user_id, provider) constraint exists, so a second
        # distinct provider account would make later per-user lookups
        # (which have no ORDER BY) nondeterministic. Refuse it instead.
        existing = await db.scalar(
            select(OAuthAccount.id).where(
                OAuthAccount.user_id == uid,
                OAuthAccount.provider == oauth_provider,
            )
        )
        if existing is not None:
            raise IntegrationError(
                "provider_already_connected",
                f"A different {oauth_provider} account is already connected.",
            )
        account = OAuthAccount(
            user_id=uid,
            provider=oauth_provider,
            provider_user_id=info.provider_user_id,
            provider_email=info.email,
        )
        db.add(account)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            _log.warning(
                "attach account insert conflict for %s: %s",
                oauth_provider,
                type(exc.orig).__name__,
            )
            raise IntegrationError(
                "account_already_linked",
                f"This {oauth_provider} account is already linked to a different user.",
            ) from exc
    else:
        account.provider_email = info.email

    encrypted_access = encrypt(bundle.access_token)
    encrypted_refresh = encrypt(bundle.refresh_token) if bundle.refresh_token else None
    token_row = (
        None
        if is_new_account
        else await db.scalar(
            select(OAuthToken).where(OAuthToken.oauth_account_id == account.id)
        )
    )
    if token_row is None:
        db.add(
            OAuthToken(
                oauth_account_id=account.id,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                token_expires_at=bundle.expires_at,
                scopes=bundle.scopes,
            )
        )
    else:
        token_row.encrypted_access_token = encrypted_access
        if encrypted_refresh is not None:
            token_row.encrypted_refresh_token = encrypted_refresh
        token_row.token_expires_at = bundle.expires_at
        token_row.scopes = bundle.scopes
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _log.warning(
            "attach token commit conflict for %s: %s",
            oauth_provider,
            type(exc.orig).__name__,
        )
        raise IntegrationError(
            "account_already_linked",
            f"This {oauth_provider} account is already linked to a different user.",
        ) from exc


async def complete_personal_attach(
    *,
    user: User,
    slug: str,
    oauth_provider: str,
    code: str,
    db: AsyncSession,
) -> str:
    """Exchange the code and store tokens ONLY for `user`. Returns provider email."""
    provider = _get_provider_for_attach(oauth_provider)
    try:
        bundle = await provider.exchange_code(code)
        info = await provider.fetch_user_info(bundle.access_token)
    except (OAuthError, httpx.HTTPError, ValueError, KeyError) as exc:
        # Log the exception type only: messages/URLs may echo secrets.
        _log.warning(
            "attach exchange failed for %s: %s", oauth_provider, type(exc).__name__
        )
        if isinstance(exc, OAuthError) and "email" in str(exc).lower():
            raise IntegrationError(
                "provider_email_unverified",
                "The provider account has no verified primary email.",
            ) from exc
        raise IntegrationError(
            "token_exchange_failed", "Could not complete the connection."
        ) from exc
    await _attach_account_to_user(
        user_id=str(user.id),
        oauth_provider=oauth_provider,
        info=info,
        bundle=bundle,
        db=db,
    )
    try:
        result = await upsert_personal_integration(
            user=user, db=db, slug=slug, oauth_provider=oauth_provider
        )
    except SQLAlchemyError as exc:
        # Tokens are already committed and the one-time code is spent, so a
        # plain retry cannot work. The existing-account path of Connect
        # finishes this step without another provider round trip.
        await db.rollback()
        _log.error("attach integration save failed for %s", oauth_provider)
        raise IntegrationError(
            "integration_save_failed",
            "Your account was linked. Click Connect once more to finish.",
        ) from exc
    if result.needs_oauth_attach:
        _log.error(
            "attach for %s stored tokens but account row not visible", oauth_provider
        )
        raise IntegrationError("attach_failed", "Account was not linked.")
    return info.email


# Re-export the pending helpers so existing router imports of the form
# `from ._attach import peek_attach_pending` continue to resolve without
# change. New code should import directly from _pending.
__all__ = [
    "ATTACH_PROVIDERS",
    "attach_redirect_uri",
    "complete_personal_attach",
    "connect_personal_oauth",
    "consume_attach_pending",
    "decrypt_pending_code",
    "peek_attach_pending",
    "start_personal_oauth_attach",
    "store_attach_pending",
]
