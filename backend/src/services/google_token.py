"""Retrieve and refresh a valid Google access token for a user.

Tokens are stored encrypted (AES-GCM) in oauth_tokens.  This module
decrypts, checks expiry (with a 60-second buffer), and silently
refreshes via the Google token endpoint when needed.

Raises TokenUnavailableError when no usable token exists so callers
can gracefully fall back to cached/mock data instead of crashing.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.crypto import TokenDecryptError, decrypt, encrypt
from ..models.oauth_account import OAuthAccount
from ..models.oauth_token import OAuthToken

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_EXPIRY_BUFFER_SECONDS = 60


class TokenUnavailableError(Exception):
    """No usable Google token exists for this user — caller should fall back."""


async def get_valid_google_token(user_id: uuid.UUID, db: AsyncSession) -> str:
    """Return a valid Google access token, refreshing it if within expiry buffer."""
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user_id,
            OAuthAccount.provider == "google",
        )
    )
    if account is None:
        raise TokenUnavailableError("No Google account linked for this user.")

    token_row = await db.scalar(
        select(OAuthToken).where(OAuthToken.oauth_account_id == account.id)
    )
    if token_row is None:
        raise TokenUnavailableError("No token row found for this Google account.")

    try:
        access_token = decrypt(token_row.encrypted_access_token)
    except TokenDecryptError as exc:
        raise TokenUnavailableError("Access token decryption failed.") from exc

    if _is_expiring(token_row.token_expires_at):
        access_token = await _refresh(token_row, db)

    return access_token


def _is_expiring(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
    return remaining < _EXPIRY_BUFFER_SECONDS


async def _refresh(token_row: OAuthToken, db: AsyncSession) -> str:
    if token_row.encrypted_refresh_token is None:
        raise TokenUnavailableError("Token expired and no refresh token is stored.")
    try:
        refresh_token = decrypt(token_row.encrypted_refresh_token)
    except TokenDecryptError as exc:
        raise TokenUnavailableError("Refresh token decryption failed.") from exc

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            },
        )
    resp.raise_for_status()
    data = resp.json()

    new_access = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    token_row.encrypted_access_token = encrypt(new_access)
    token_row.token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=expires_in
    )
    await db.commit()
    return new_access
