"""Auth service — link/create user + persist encrypted tokens.

This is the only place that knows the user/account/token co-ordination.
Routers call ``upsert_user_from_oauth`` and get back a User row ready
for JWT issuance.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.oauth_account import OAuthAccount
from ..models.oauth_token import OAuthToken
from ..models.user import User
from .crypto import encrypt
from .providers.base import OAuthTokenBundle, OAuthUserInfo


async def upsert_user_from_oauth(
    db: AsyncSession,
    *,
    provider: str,
    info: OAuthUserInfo,
    bundle: OAuthTokenBundle,
) -> User:
    """Find-or-create the user, link the oauth_account, persist encrypted tokens.

    Linking rule: if (provider, provider_user_id) already exists -> update its
    user. Else if a user with the same lowered email exists -> link to that
    user (multi-provider for one human). Else -> create a new user row.
    """
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == info.provider_user_id,
        )
    )
    if account is not None:
        user = await db.scalar(select(User).where(User.id == account.user_id))
        assert user is not None  # FK guarantees this
        _refresh_user_profile(user, info)
        account.provider_email = info.email
    else:
        user = await db.scalar(select(User).where(User.email == info.email))
        if user is None:
            user = User(email=info.email, name=info.name, avatar_url=info.avatar_url)
            db.add(user)
            await db.flush()
        else:
            _refresh_user_profile(user, info)
        account = OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=info.provider_user_id,
            provider_email=info.email,
        )
        db.add(account)
        await db.flush()

    token_row = await db.scalar(
        select(OAuthToken).where(OAuthToken.oauth_account_id == account.id)
    )
    encrypted_access = encrypt(bundle.access_token)
    encrypted_refresh = encrypt(bundle.refresh_token) if bundle.refresh_token else None
    if token_row is None:
        token_row = OAuthToken(
            oauth_account_id=account.id,
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypted_refresh,
            token_expires_at=bundle.expires_at,
            scopes=bundle.scopes,
        )
        db.add(token_row)
    else:
        token_row.encrypted_access_token = encrypted_access
        if encrypted_refresh is not None:
            token_row.encrypted_refresh_token = encrypted_refresh
        token_row.token_expires_at = bundle.expires_at
        token_row.scopes = bundle.scopes

    await db.commit()
    return user


def _refresh_user_profile(user: User, info: OAuthUserInfo) -> None:
    if info.name and not user.name:
        user.name = info.name
    if info.avatar_url and not user.avatar_url:
        user.avatar_url = info.avatar_url
