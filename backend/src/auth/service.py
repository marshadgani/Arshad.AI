"""Auth service — link/create user + persist encrypted tokens.

This is the only place that knows the user/account/token co-ordination.
Routers call ``upsert_user_from_oauth`` and get back a User row ready
for JWT issuance.

Concurrency: two simultaneous OAuth callbacks for the same identity
(rapid double-click on "Continue with Google", or Google + GitHub for
the same email landing within milliseconds) race on the SELECT-then-
INSERT pattern. We retry once on IntegrityError — the second pass sees
the row the first one inserted and goes down the update branch.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.oauth_account import OAuthAccount
from ..models.oauth_token import OAuthToken
from ..models.user import User
from .attach_state import AttachError
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
    try:
        return await _upsert_once(db, provider=provider, info=info, bundle=bundle)
    except IntegrityError:
        await db.rollback()
        # Second pass: the row we lost the race to is now visible. The
        # account/user SELECT branches will hit existing rows.
        return await _upsert_once(db, provider=provider, info=info, bundle=bundle)


async def _upsert_once(
    db: AsyncSession,
    *,
    provider: str,
    info: OAuthUserInfo,
    bundle: OAuthTokenBundle,
) -> User:
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


async def attach_oauth_account_to_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | str,
    provider: str,
    info: OAuthUserInfo,
    bundle: OAuthTokenBundle,
) -> OAuthAccount:
    """Attach a provider identity to an ALREADY-KNOWN, already-authenticated
    user — the "connect an additional provider" counterpart to
    upsert_user_from_oauth.

    Deliberately does NOT reuse upsert_user_from_oauth: that function
    find-or-creates a *user* by email (service.py `_upsert_once`) and
    would create a brand-new user, or silently link this provider grant
    onto a DIFFERENT existing user who happens to share that email —
    exactly the account-confusion bug this flow exists to avoid. Here the
    target user is fixed by the caller (recovered from a signed, single-
    use, user-bound attach-state token — see auth/attach_state.py), and
    this function only ever writes oauth_accounts/oauth_tokens for that
    one user_id. It never touches the users row (no email/name/avatar
    writes) and never mints a JWT.
    """
    try:
        return await _attach_once(
            db, user_id=user_id, provider=provider, info=info, bundle=bundle
        )
    except IntegrityError:
        await db.rollback()
        return await _attach_once(
            db, user_id=user_id, provider=provider, info=info, bundle=bundle
        )


async def _attach_once(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | str,
    provider: str,
    info: OAuthUserInfo,
    bundle: OAuthTokenBundle,
) -> OAuthAccount:
    target_user_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id)

    # SI-1: this provider identity must not already belong to someone else.
    existing_by_identity = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == info.provider_user_id,
        )
    )
    if (
        existing_by_identity is not None
        and existing_by_identity.user_id != target_user_id
    ):
        raise AttachError(
            "account_owned_by_another_user",
            f"This {provider} account is already linked to a different Arshad.AI user.",
        )

    # SI-2: this user must not already have a DIFFERENT provider identity
    # linked for the same provider — get_access_token's (user_id, provider)
    # lookup would otherwise be ambiguous between two oauth_accounts rows.
    existing_for_user = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == target_user_id,
            OAuthAccount.provider == provider,
        )
    )
    if (
        existing_for_user is not None
        and existing_for_user.provider_user_id != info.provider_user_id
    ):
        raise AttachError(
            "provider_already_linked",
            f"A different {provider} account is already linked to this user.",
        )

    account = existing_by_identity or existing_for_user
    if account is None:
        account = OAuthAccount(
            user_id=target_user_id,
            provider=provider,
            provider_user_id=info.provider_user_id,
            provider_email=info.email,
        )
        db.add(account)
        await db.flush()
    else:
        # SI-4: never touch the users row here — a different email on the
        # attached identity is expected and must not change login identity.
        account.provider_email = info.email

    token_row = await db.scalar(
        select(OAuthToken).where(OAuthToken.oauth_account_id == account.id)
    )
    encrypted_access = encrypt(bundle.access_token)
    encrypted_refresh = encrypt(bundle.refresh_token) if bundle.refresh_token else None
    if token_row is None:
        token_row = OAuthToken(
            oauth_account_id=account.id,
            encrypted_access_token=encrypted_access,
            # SI-3: only ever set on creation here, or conditionally on
            # update below — a provider omitting refresh_token on
            # re-consent (Google without a first-time grant, GitHub always)
            # must never null out a refresh token already on file.
            encrypted_refresh_token=encrypted_refresh,
            token_expires_at=bundle.expires_at,
            scopes=bundle.scopes,  # SI-5: verbatim grant, not the requested set
        )
        db.add(token_row)
    else:
        token_row.encrypted_access_token = encrypted_access
        if encrypted_refresh is not None:
            token_row.encrypted_refresh_token = encrypted_refresh
        token_row.token_expires_at = bundle.expires_at
        token_row.scopes = bundle.scopes

    await db.commit()
    await db.refresh(account)
    return account
