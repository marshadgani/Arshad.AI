"""Authenticated "attach a provider to the signed-in user" OAuth flow.

Used by the six personal providers (GitHub, Gmail, Google Calendar/Drive/
Tasks/YouTube) when the signed-in user has no oauth_account for the
provider (e.g. they logged in with Google and now connect GitHub).

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

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import encrypt
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
    backend = os.getenv("BACKEND_URL", "").rstrip("/")
    if not backend:
        raise IntegrationError(
            "backend_url_not_configured", "OAuth redirect is not configured."
        )
    return f"{backend}/api/v1/integrations/personal/attach/{oauth_provider}/callback"


def _get_provider_for_attach(oauth_provider: str) -> OAuthProvider:
    provider: GitHubOAuthProvider | GoogleOAuthProvider
    if oauth_provider == "github":
        provider = GitHubOAuthProvider()
    elif oauth_provider == "google":
        provider = GoogleOAuthProvider()
    else:
        raise IntegrationError(
            "unsupported_oauth_provider", f"Unsupported provider '{oauth_provider}'."
        )
    # Same redirect_uri must be used for the authorize URL and the token
    # exchange; both go through this factory.
    provider.redirect_uri = attach_redirect_uri(oauth_provider)
    return provider


# ── Flow orchestration ────────────────────────────────────────────────────


async def start_personal_oauth_attach(
    *, user_id: str, slug: str, oauth_provider: str
) -> ConnectResult:
    provider = _get_provider_for_attach(oauth_provider)
    state = await store_oauth_state(
        user_id=user_id, slug=slug, ctx={"oauth_provider": oauth_provider}
    )
    return ConnectResult(redirect_url=provider.authorization_url(state))


async def connect_personal_oauth(
    *, user: User, db: AsyncSession, slug: str, oauth_provider: str
) -> ConnectResult:
    """Existing-account path unchanged; otherwise start the attach flow."""
    result = await upsert_personal_integration(
        user=user, db=db, slug=slug, oauth_provider=oauth_provider
    )
    if result.needs_oauth_attach:
        return await start_personal_oauth_attach(
            user_id=str(user.id), slug=slug, oauth_provider=oauth_provider
        )
    return result


# ── Account and token persistence ────────────────────────────────────────


async def _attach_account_to_user(
    *,
    user_id: str,
    oauth_provider: str,
    info: OAuthUserInfo,
    bundle: OAuthTokenBundle,
    db: AsyncSession,
) -> None:
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
            raise IntegrationError(
                "account_already_linked",
                f"This {oauth_provider} account is already linked to a different user.",
            ) from exc
    else:
        account.provider_email = info.email

    encrypted_access = encrypt(bundle.access_token)
    encrypted_refresh = encrypt(bundle.refresh_token) if bundle.refresh_token else None
    token_row = await db.scalar(
        select(OAuthToken).where(OAuthToken.oauth_account_id == account.id)
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
    except (OAuthError, httpx.HTTPError) as exc:
        # Log the exception type only: messages/URLs may echo secrets.
        _log.warning(
            "attach exchange failed for %s: %s", oauth_provider, type(exc).__name__
        )
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
    result = await upsert_personal_integration(
        user=user, db=db, slug=slug, oauth_provider=oauth_provider
    )
    if result.needs_oauth_attach:
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
