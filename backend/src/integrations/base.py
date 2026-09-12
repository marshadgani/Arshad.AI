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

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import Integration
from ..models.user import User

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
    rows_written: int
    summary: str
    duration_ms: int


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

    async def disconnect(self, *, integration: Integration, db: AsyncSession) -> None:
        """Default: mark integration disconnected. Subclasses can override
        to revoke tokens upstream when the provider supports it."""
        integration.status = "disconnected"
        integration.last_error = None
        await db.commit()
