"""Which OAuth scope each login-backed personal integration requires.

Split out of `_shared.py` so that the *policy* ("gmail needs
gmail.modify") is stated in one small, readable place, separate from the
*mechanics* that act on it (starting an attach flow, writing an
Integration row, deriving a status). Two unrelated consumers read this
policy — the connect path and the status path — and neither needs to know
how the other behaves.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.providers import GoogleOAuthProvider
from ...models.oauth_account import OAuthAccount
from ...models.oauth_token import OAuthToken

# The scope each slug's tools actually need. None = no specific scope
# required beyond having the account linked at all (GitHub's OAuth App
# scope is requested wholesale at login; there is no per-integration
# sub-scope to gate on). Used both to detect the scope-gap attach branch
# and to power the "Re-auth required" status in status_from_oauth_account.
REQUIRED_SCOPE_BY_SLUG: Final[dict[str, str | None]] = {
    "github": None,
    "google_calendar": "https://www.googleapis.com/auth/calendar.events",
    "gmail": "https://www.googleapis.com/auth/gmail.modify",
    "google_drive": "https://www.googleapis.com/auth/drive.metadata.readonly",
    "google_tasks": "https://www.googleapis.com/auth/tasks",
    "youtube": "https://www.googleapis.com/auth/youtube.readonly",
}


def _assert_required_scopes_are_requestable() -> None:
    """Import-time guard: every non-None value above must be a scope
    GoogleOAuthProvider actually requests, or this map and google.py's
    _SCOPES have drifted apart and the scope-gap branch would loop
    forever — the user re-consents, Google still can't grant a scope
    nobody asked for, and status stays 'expired' permanently."""
    requestable = set(GoogleOAuthProvider.scopes)
    for slug, scope in REQUIRED_SCOPE_BY_SLUG.items():
        if scope is not None and scope not in requestable:
            raise RuntimeError(
                f"REQUIRED_SCOPE_BY_SLUG['{slug}'] = {scope!r} is not in "
                f"GoogleOAuthProvider.scopes — fix the drift before deploying."
            )


_assert_required_scopes_are_requestable()


async def has_scope_gap(account: OAuthAccount, slug: str, db: AsyncSession) -> bool:
    """True when `account`'s stored grant cannot serve `slug`'s tools.

    A missing token row counts as a gap: the account exists but carries no
    usable grant, which is indistinguishable from an unscoped one as far
    as every caller is concerned.
    """
    required = REQUIRED_SCOPE_BY_SLUG.get(slug)
    if required is None:
        return False
    token = await db.scalar(
        select(OAuthToken).where(OAuthToken.oauth_account_id == account.id)
    )
    if token is None:
        return True
    return required not in (token.scopes or [])
