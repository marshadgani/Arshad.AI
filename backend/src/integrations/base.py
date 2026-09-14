"""Integration ABC + shared types.

Every provider (personal/* or project/*) subclasses IntegrationProvider and
registers via @register. Two kinds of providers:

- personal_oauth — per-user Google / GitHub / Spotify / Strava / etc.
  connect() kicks off OAuth (returns a redirect URL); the provider's
  callback handler does the rest. Credential storage is NOT uniform across
  this kind: the six Google/GitHub providers built on personal/_shared.py
  (gmail, google_calendar, google_drive, google_tasks, youtube, github)
  reuse the login-time grant in oauth_accounts + oauth_tokens and never
  create an integration_oauth_tokens row; every other personal_oauth
  provider (Spotify, Strava, Whoop, ...) is built on
  personal/_oauth_base.OAuthIntegrationProvider and stores its own row in
  integration_oauth_tokens, keyed by integration_id.

- project_apikey / personal_apikey — Render / Vercel / Supabase / Plaid /
  etc. connect() takes an API key in the payload, validates it via a probe
  request, encrypts and stores via api_key_credentials.

disconnect() unconditionally scrubs whichever of those tables actually
holds this integration's credential and, where the provider declares
support, best-effort revokes the credential with the third party too. The
workflow itself lives in integrations/disconnect.py (FEAT-145) — this
module only declares the contract providers implement; the types it
defines are re-exported here so `from .base import DisconnectOutcome`
keeps working for the ~44 provider modules and the router.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import Integration
from ..models.user import User
from .disconnect import (
    DisconnectOutcome,
    RevocationKind,
    UpstreamRevocationResult,
    run_disconnect,
)

__all__ = [
    "ConnectResult",
    "DisconnectOutcome",
    "IntegrationError",
    "IntegrationKind",
    "IntegrationProvider",
    "IntegrationStatus",
    "RevocationKind",
    "StatusReport",
    "SyncResult",
    "UpstreamRevocationResult",
]

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
    """mode/job_id (FEAT-144): DAG-backed providers (google_calendar, gmail,
    github) only enqueue a background job — they never do the real
    ingestion synchronously. mode='enqueued' + job_id lets the router and
    frontend tell that apart from a provider that actually did the work
    before returning (mode='completed', the default). Both fields default
    safely so every pre-existing synchronous provider is unaffected."""

    rows_written: int
    summary: str
    duration_ms: int
    mode: Literal["completed", "enqueued"] = "completed"
    job_id: str | None = None


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
    # DAG-id this provider's sync() enqueues via make_sync_via_dag(), or
    # None for every synchronously-syncing provider. This is the single
    # declaration of the slug<->dag_id relationship (FEAT-144): the
    # router's is-pollable check, the status query's dag_id filter, and
    # registry.slug_for_dag_id()'s reverse lookup all derive from it —
    # nothing else declares or re-derives this mapping.
    sync_dag_id: ClassVar[str | None] = None
    # FEAT-145: declares what disconnect() should attempt upstream. The
    # safe default is deliberate — making this a required declaration would
    # crash the whole app on boot the moment one of the 44 providers forgot
    # it. Completeness is enforced instead by the registry walk in
    # backend/tests/test_integration_disconnect.py, which fails CI.
    revocation_kind: ClassVar[RevocationKind] = "no_revoke"

    @abstractmethod
    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        """Start a connection. For OAuth, returns the auth URL.
        For API-key, validates and stores the key."""

    @abstractmethod
    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        """Pull fresh data into ingested_* tables (personal) or refresh
        cached status (project)."""

    @abstractmethod
    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        """Health check + most recent sync metadata."""

    async def _prepare_revocation(
        self, *, integration: Integration, db: AsyncSession
    ) -> Any | None:
        """Load+decrypt whatever the upstream revoke call needs, while the
        read transaction opened by that lookup is still open. Returns an
        opaque payload for _revoke_upstream(), or None when there is
        nothing to revoke (no credential row, provider doesn't support
        revocation, or decryption failed). Default: nothing to revoke.
        """
        return None

    async def _revoke_upstream(self, *, payload: Any) -> UpstreamRevocationResult:
        """Pure network call — deliberately takes no db handle, so a
        subclass cannot re-open a transaction mid-network-call (the bug
        class that motivated splitting this from _prepare_revocation).
        Default: nothing to revoke.
        """
        return "unsupported"

    async def disconnect(
        self, *, integration: Integration, db: AsyncSession
    ) -> DisconnectOutcome:
        """Revoke the upstream credential where the provider supports it,
        then scrub every locally stored credential row and mark the
        integration disconnected — keeping the frontend's disconnect-dialog
        promise for every provider, not just the ones that override this.

        Providers customise the two hooks above rather than this method;
        the sequencing lives in integrations/disconnect.run_disconnect.
        """
        return await run_disconnect(self, integration=integration, db=db)
