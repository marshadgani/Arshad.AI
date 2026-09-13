"""Read-side queries backing the dashboard widgets — principally the
ingested_* tables, plus the one identity read (``fetch_github_provider_user_id``)
required to interpret ingested GitHub rows. That function is a plain
unencrypted scalar read: it never decrypts a token and never raises on an
unlinked account; token handling stays in ``auth/``.

This module owns *how* dashboard rows are fetched: the predicates, the
ordering, and the row caps. ``api/v1/dashboard.py`` owns *what* to do with
them (derive → serialise → seed fallback) and no longer constructs
SQLAlchemy statements against the ingestion tables itself.

Why the separation matters here specifically: each predicate below is
deliberately shaped to match an index declared in ``models/ingested.py``
(see ``ix_ingested_gmail_flagged_user_occurred`` and
``ix_ingested_github_user_kind_occurred``). Keeping the predicates in one
module next to that stated coupling makes an accidental divergence — which
silently degrades to a sequential scan rather than failing — visible in a
single file rather than spread across three route handlers.

Every function is a plain read: no derivation, no serialisation, no
exception swallowing. A DB failure propagates so it surfaces as a 500
rather than being masked as an empty widget.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.ingested import (
    GMAIL_FLAGGED_LABELS_PREDICATE,
    GitHubActivityKind,
    IngestedGitHubActivity,
    IngestedGmailThread,
)
from src.models.oauth_account import OAuthAccount

# Row cap for the widget queries below — pagination deferred, see CNR-004.
# At single-user scale a LIMIT is sufficient; do not read this as "fully
# index-served" (the JSONB predicate on flagged Gmail threads is a
# post-index filter step).
LIVE_ROW_LIMIT = 50

# A dedicated, smaller cap for the GitHub activity feed widget (FEAT-139)
# because it renders a compact card, not a full list view.
GITHUB_ACTIVITY_LIMIT = 12


async def fetch_flagged_gmail_threads(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = LIVE_ROW_LIMIT,
) -> Sequence[IngestedGmailThread]:
    """Most recent Gmail threads carrying a non-empty ``_derived.labels``
    array.

    The filter is ``GMAIL_FLAGGED_LABELS_PREDICATE`` — the *same constant*
    that defines the partial index ``ix_ingested_gmail_flagged_user_occurred``
    (``models/ingested.py``). Within it, ``jsonb_typeof(...) = 'array'``
    guards against a non-array value in the untrusted JSONB payload reaching
    ``jsonb_array_length`` (which raises on a scalar) — a type guard, not a
    business filter; ``jsonb_array_length(...) > 0`` is the business filter
    that keeps empty-labelled (``[]``) threads from surfacing as tasks.

    Sharing one constant is what keeps the index usable: Postgres only
    applies a partial index when the query's WHERE clause is provably
    implied by the index predicate, and the obvious ORM spelling compiles
    the JSON path keys to bind parameters, which defeats that proof. See
    the constant's own comment for the full reasoning — do not "modernise"
    this back to ``IngestedGmailThread.raw["_derived"]["labels"]``.

    ``user_id`` remains a bound parameter; the literal fragment carries no
    user input.
    """
    result = await db.execute(
        select(IngestedGmailThread)
        .where(
            IngestedGmailThread.user_id == user_id,
            text(GMAIL_FLAGGED_LABELS_PREDICATE),
        )
        .order_by(IngestedGmailThread.occurred_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def fetch_github_activity_by_kind(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: GitHubActivityKind,
    *,
    limit: int = LIVE_ROW_LIMIT,
) -> Sequence[IngestedGitHubActivity]:
    """Most recent GitHub rows of a single ``kind``.

    Three callers. ``/notifications`` takes ``kind='issue'``.
    ``/agent-activity`` and ``/decisions`` both take ``kind='pr'``,
    deliberately: ``/agent-activity`` shows every recent PR, ``/decisions``
    shows the strict subset that is blocked on this user (open, non-draft,
    and either awaiting their review or authored by them with no
    outstanding review requests). The subset relationship is intentional —
    do not deduplicate, and do not read the overlap as a bug.

    Only the ``limit`` most-recently-UPDATED PRs are visible to any caller
    (default ``LIVE_ROW_LIMIT`` = 50). A PR older than that window is
    invisible to ``/decisions`` even if it is blocked on the user.
    Acceptable at single-user scale; revisit with CNR-004 pagination.
    """
    result = await db.execute(
        select(IngestedGitHubActivity)
        .where(
            IngestedGitHubActivity.user_id == user_id,
            IngestedGitHubActivity.kind == kind,
        )
        .order_by(IngestedGitHubActivity.occurred_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def fetch_github_provider_user_id(
    db: AsyncSession, user_id: uuid.UUID
) -> str | None:
    """The user's GitHub numeric account id (as a string), or ``None`` when
    GitHub is not linked.

    Plain unencrypted scalar read against ``oauth_accounts`` — never
    decrypts an OAuth token, never raises when GitHub isn't linked. Used
    only to interpret ``raw['user']['id']`` / ``raw['requested_reviewers']``
    on ingested GitHub PR rows for the ``/decisions`` widget.

    ``oauth_accounts`` is unique on ``(provider, provider_user_id)``, NOT
    ``(user_id, provider)`` — nothing in the schema prevents two GitHub
    accounts being linked to the same user. ``order_by(created_at).limit(1)``
    makes the read deterministic (oldest link wins) instead of risking
    ``MultipleResultsFound`` on ``scalar_one_or_none``. Whether a user
    should be allowed to link two GitHub accounts is a separate product
    question, not answered here.
    """
    result = await db.execute(
        select(OAuthAccount.provider_user_id)
        .where(OAuthAccount.user_id == user_id, OAuthAccount.provider == "github")
        .order_by(OAuthAccount.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_recent_github_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = GITHUB_ACTIVITY_LIMIT,
) -> Sequence[IngestedGitHubActivity]:
    """Most recent GitHub rows of any kind, for the combined activity feed."""
    result = await db.execute(
        select(IngestedGitHubActivity)
        .where(IngestedGitHubActivity.user_id == user_id)
        .order_by(IngestedGitHubActivity.occurred_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
