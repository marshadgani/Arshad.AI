"""Integration ABC + shared types.

Every provider (personal/* or project/*) subclasses IntegrationProvider and
registers via @register. Two kinds of providers:

- personal_oauth — per-user Google / GitHub / Notion / Slack / etc.
  connect() kicks off OAuth (returns a redirect URL); the provider's
  existing OAuth callback handler does the rest. State is stored in the
  existing oauth_accounts + oauth_tokens tables.

- project_apikey — Render / Vercel / Supabase / Upstash / etc.
  connect() takes an API key in the payload, validates it via a probe
  request, encrypts and stores via api_key_credentials.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import Integration
from ..models.user import User
from ..services.integration_credentials import scrub_credentials

_log = logging.getLogger(__name__)

IntegrationKind = Literal[
    "personal_oauth", "personal_apikey", "project_apikey", "static", "personal_push"
]
IntegrationStatus = Literal[
    "connected", "disconnected", "error", "expired", "coming_soon"
]


class IntegrationError(Exception):
    """Mapped to 400/422 by the router."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def safe_detail(exc: BaseException) -> str:
    """A client-safe one-line description of a failed outbound call.

    Deliberately never interpolates ``str(exc)``. httpx embeds the *full
    request URL* in the message of both HTTPStatusError and RequestError,
    and several providers authenticate via the query string
    (OpenWeatherMap ``?appid=``, Stack Exchange ``?access_token=``). The
    old ``f"{type(exc).__name__}: {exc}"`` shape therefore wrote a
    plaintext credential into ``integration.last_error`` — a column
    returned verbatim by ``GET /api/v1/integrations/{slug}/status`` — and
    into the 400 body of the failing sync. That defeats the whole
    AES-GCM-at-rest design in auth/crypto.py.

    The upstream status code is kept because it is the one detail that is
    actionable and provably credential-free; everything else belongs in
    the server-side log, where the caller logs the real exception.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTPStatusError: upstream returned {exc.response.status_code}"
    return type(exc).__name__


@dataclass(frozen=True)
class UpstreamRevocation:
    """What `disconnect()` is able to promise about the *third party*.

    Deleting our copy of a credential and getting the provider to stop
    honouring it are two different things, and only the provider knows
    which of them it can do. Before this type existed, that fact was
    unrecorded: `_revoke_upstream()` defaulted to a silent no-op, every
    provider inherited it, and the disconnect dialog told all of them
    "revoked with the provider" — true for none.

    Two states, and no third: either we call something upstream
    (`supported=True`, `detail` naming what), or we cannot
    (`supported=False`, `detail` saying why and what the user must do
    themselves). `detail` is required in both, because "we can't" without
    a reason is indistinguishable from "nobody checked" — which is the
    bug. Build these through `revokes_via()` / `cannot_revoke()` rather
    than the constructor, so the two states read as two named intentions
    at every declaration site.

    Surfaced to the frontend by presenters.provider_descriptor() so the
    confirmation dialog states what will actually happen for *this*
    provider instead of one blanket claim for all of them.
    """

    supported: bool
    detail: str


def revokes_via(detail: str) -> UpstreamRevocation:
    """This provider has a revocation endpoint and disconnect() calls it.

    `detail` names the call (e.g. "POST https://api.fitbit.com/oauth2/revoke")
    so a reviewer can check the claim against the provider's docs without
    reading the implementation.
    """
    return UpstreamRevocation(supported=True, detail=detail)


def cannot_revoke(detail: str) -> UpstreamRevocation:
    """This provider's credential cannot (or must not) be revoked by us.

    Three legitimate shapes, all requiring the same honesty in the UI:
    the provider publishes no revocation endpoint (Spotify, Shopify); the
    credential is a shared grant revoking which would break unrelated
    things (Google, GitHub — see BR-005); or there is nothing upstream
    that trusts it in the first place (Apple Health's inbound push token,
    the static no-auth providers).

    `detail` is shown to the user, so write it as the action they must
    take themselves, not as an apology.
    """
    return UpstreamRevocation(supported=False, detail=detail)


# Nothing upstream ever trusted the credential, so there is nothing to
# revoke — not a limitation, just an absence. Shared by the static
# providers and by Apple Health's inbound-only ingest token.
NOTHING_TO_REVOKE = cannot_revoke(
    "Nothing is revoked with a third party because no third-party "
    "credential is stored for this integration."
)


@dataclass
class ConnectResult:
    """Returned by connect(). For OAuth providers, redirect_url is the
    URL the frontend must navigate the browser to. For API-key providers,
    the integration is already connected — redirect_url is None.

    integration_id: None when connect() hands control to an OAuth
    redirect before any Integration row exists yet (the row is created
    later, in the callback). Previously this was modelled as "" (empty
    string) rather than None — a classic weak-type sentinel that let a
    real (if degenerate) empty string collide with "no id yet" and gave
    every caller one more falsy-string case to reason about instead of a
    single None check. str | None makes "no id yet" and "an id" the only
    two representable states.

    ingest_token: one-time-display bearer secret for webhook/push-style
    providers (e.g. Apple Health via an iOS Shortcut) that need to hand
    the user a token to paste into an external tool. None for every other
    provider kind. MUST NOT be logged — repr is suppressed on this field
    specifically so it can never leak via a log line, an exception
    message, or an error-tracking breadcrumb that dumps the dataclass.

    Invariant: redirect_url and ingest_token are mutually exclusive — a
    provider is either handing the browser off to an external OAuth flow
    or handing the user a token to paste elsewhere, never both. This was
    previously unenforced (any provider could set both, or a new provider
    kind could get it wrong with no error until a confused frontend
    branch); __post_init__ makes the illegal combination unconstructible
    instead of a possibility every consumer has to defend against.
    """

    integration_id: str | None = None
    redirect_url: str | None = None
    ingest_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.redirect_url is not None and self.ingest_token is not None:
            raise ValueError(
                "ConnectResult cannot carry both redirect_url and ingest_token "
                "— a provider hands the user off to OAuth or hands them a "
                "token to paste elsewhere, never both."
            )


@dataclass
class SyncResult:
    rows_written: int
    summary: str
    duration_ms: int


@dataclass
class EnqueuedResult:
    """Returned by sync() for queue/DAG-backed providers instead of a
    fabricated SyncResult. 'rows_written' would be a lie here — nothing
    has been processed yet, only enqueued — so it is deliberately not a
    field on this type. The router uses the SyncResult | EnqueuedResult
    union to emit an honest `mode` discriminator to the frontend.
    """

    job_id: str
    dag_id: str
    summary: str
    deduped: bool = False


@dataclass
class StatusReport:
    status: IntegrationStatus
    last_synced_at: str | None
    last_error: str | None
    extra: dict[str, Any]


class IntegrationProvider(ABC):
    slug: ClassVar[str]
    kind: ClassVar[IntegrationKind]
    display_name: ClassVar[str]
    category: ClassVar[str]
    description: ClassVar[str]
    docs_url: ClassVar[str | None] = None
    icon: ClassVar[str] = ""  # short identifier the frontend maps to a glyph
    coming_soon: ClassVar[bool] = False
    coming_soon_reason: ClassVar[str | None] = None
    # When set, the frontend shows a domain/account-input modal before
    # kicking off connect() instead of POSTing an empty payload straight
    # away. None (default) for every provider that needs no extra input —
    # emitted unconditionally by _provider_descriptor() so it reaches the
    # frontend even for a provider the user has never connected.
    connect_prompt: ClassVar[dict[str, str] | None] = None
    # What disconnect() does with the third party, and what the UI is
    # therefore allowed to promise. Deliberately has NO default: a
    # provider that never declares it fails at import time in
    # registry.register(), because the silent default is exactly how
    # every provider ended up inheriting a no-op revocation while the
    # disconnect dialog claimed otherwise. Declaring `cannot_revoke(...)`
    # is cheap; forgetting to think about it must not be.
    upstream_revocation: ClassVar[UpstreamRevocation]
    # Set by queue/DAG-backed providers (google_calendar, gmail, github) so
    # routers.py and services/ingestion/dag_map.py can resolve "does this
    # provider have a pollable job status?" without a slug allowlist.
    # None (default) means sync() is synchronous — no job to poll.
    sync_dag_id: ClassVar[str | None] = None

    @abstractmethod
    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        """Start a connection. For OAuth, returns the auth URL.
        For API-key, validates and stores the key."""

    @abstractmethod
    async def sync(
        self, *, integration: Integration, db: AsyncSession
    ) -> SyncResult | EnqueuedResult:
        """Pull fresh data into ingested_* tables (personal) or refresh
        cached status (project). Providers with sync_dag_id set MUST
        return EnqueuedResult — the actual work happens asynchronously via
        the queue worker / Airflow, which is the only place a truthful
        SyncResult (with a real rows_written) could come from."""

    @abstractmethod
    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        """Health check + most recent sync metadata."""

    async def _revoke_upstream(
        self, *, integration: Integration, db: AsyncSession
    ) -> None:
        """Tell the third-party provider to stop trusting this credential
        — an OAuth token-revocation call, an API-key deletion call —
        before the local copy is deleted.

        The default no-op is correct ONLY for a provider that declared
        `upstream_revocation = cannot_revoke(...)`; the pairing is
        enforced at import time by registry.register(), so a provider
        cannot claim `revokes_via(...)` in the UI and then silently
        inherit this no-op. Most OAuth providers get their implementation
        for free by declaring `revoke_url` on OAuthIntegrationProvider
        rather than overriding this at all.

        The credential rows are still on file here, so read whatever the
        revoke call needs from `db` now. Let network/API errors propagate:
        disconnect() catches and logs them, because a third party being
        unreachable must not stop us deleting the local copy.
        """
        return None

    async def disconnect(self, *, integration: Integration, db: AsyncSession) -> None:
        """Revoke the credential upstream, delete every local copy, then
        mark the integration disconnected.

        Which tables hold credential material and how each is cleared is
        not decided here — see `services/integration_credentials.py`, the
        same policy the bulk remediation script uses. The deletion and the
        status flip share one transaction and commit once, so a mid-way
        failure cannot leave credentials deleted but status "connected",
        or vice versa.

        The upstream revoke deliberately runs outside that transaction,
        and `db` may already have one open from the caller's own reads
        (AsyncSession autobegins on the first execute()) — hence the
        commit that closes it first. Holding a transaction open across a
        network call is what `.claude/rules/database.md` forbids.
        """
        if db.in_transaction():
            await db.commit()

        try:
            await self._revoke_upstream(integration=integration, db=db)
        except Exception:  # noqa: BLE001 — fail open, see below
            # The user asked us to forget their credential; an unreachable
            # provider cannot be a reason to keep it on file.
            _log.warning(
                "integration.disconnect upstream revocation failed slug=%s "
                "integration_id=%s — proceeding with local credential deletion",
                integration.slug,
                integration.id,
                exc_info=True,
            )

        try:
            counts = await scrub_credentials(db, scope=integration.id)
            integration.status = "disconnected"
            integration.last_error = None
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        # Identifiers and row counts only — never credential material.
        _log.info(
            "integration.disconnect slug=%s integration_id=%s user_id=%s "
            "api_key_rows=%d oauth_rows=%d ingest_rows_revoked=%d",
            integration.slug,
            integration.id,
            integration.user_id,
            counts.api_key_rows,
            counts.oauth_rows,
            counts.ingest_rows,
        )
