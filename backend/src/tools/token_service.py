"""Token service — decrypt + refresh OAuth tokens for tool calls.

Two responsibilities:

1. ``get_access_token(db, user, provider)`` — finds the user's oauth_account
   for the provider, decrypts the access token, returns it as a string.
   Caller (the HTTP client) detects 401 and asks for a fresh token via
   ``refresh_google_token``.

2. ``refresh_google_token(db, oauth_account_id)`` — exchanges the stored
   refresh_token for a new access_token at Google's token endpoint, encrypts
   the new value, persists, returns the plaintext access token.

GitHub OAuth Apps don't issue refresh tokens (Phase C decision), so on a
GitHub 401 the HTTP client raises ``ProviderReauthRequired('github')``
directly without calling this module.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.crypto import decrypt, encrypt
from ..auth.providers.base import required_env
from ..models.oauth_account import OAuthAccount
from ..models.oauth_token import OAuthToken
from ..models.user import User
from .base import ProviderNotLinked, ProviderReauthRequired

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


async def get_access_token(
    db: AsyncSession,
    user: User,
    provider: Literal["google", "github"],
) -> tuple[str, OAuthAccount]:
    """Returns (access_token_plaintext, account) for the user+provider pair.

    Raises ProviderNotLinked if the user has no oauth_account for this
    provider yet — the tool router maps this to 400 oauth_account_not_linked.
    """
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id,
            OAuthAccount.provider == provider,
        )
    )
    if account is None:
        raise ProviderNotLinked(provider)
    token_row = await db.scalar(
        select(OAuthToken).where(OAuthToken.oauth_account_id == account.id)
    )
    if token_row is None:
        raise ProviderNotLinked(provider)
    return decrypt(token_row.encrypted_access_token), account


async def refresh_google_token(
    db: AsyncSession,
    oauth_account_id: uuid.UUID,
) -> str:
    """Exchange the stored Google refresh_token for a new access_token.

    Persists the new (encrypted) access token + expires_at on the same
    oauth_tokens row. Returns plaintext access token.

    Raises ProviderReauthRequired('google') if Google rejects the refresh
    (refresh token revoked, scope removed, account deleted, etc.).

    Concurrency: SELECT...FOR UPDATE serialises concurrent refreshes for
    the same account. Without it, two coroutines that both observe an
    expired token would both POST to Google, both persist different new
    tokens, and the second commit would clobber the first's expiry.
    """
    token_row = await db.scalar(
        select(OAuthToken)
        .where(OAuthToken.oauth_account_id == oauth_account_id)
        .with_for_update()
    )
    if token_row is None or token_row.encrypted_refresh_token is None:
        raise ProviderReauthRequired("google")

    refresh_token = decrypt(token_row.encrypted_refresh_token)
    client_id = required_env("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = required_env("GOOGLE_OAUTH_CLIENT_SECRET")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Accept": "application/json"},
        )
    if resp.status_code in (400, 401):
        # invalid_grant — refresh token is revoked or malformed
        raise ProviderReauthRequired("google")
    resp.raise_for_status()
    data = resp.json()

    new_access = data["access_token"]
    expires_in = data.get("expires_in")
    new_expiry = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )

    token_row.encrypted_access_token = encrypt(new_access)
    token_row.token_expires_at = new_expiry
    # Google may rotate the refresh token; if a new one came back, persist it.
    if data.get("refresh_token"):
        token_row.encrypted_refresh_token = encrypt(data["refresh_token"])
    await db.commit()

    return new_access
