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

    ingest_token: one-time-display bearer secret for webhook/push-style
    providers (e.g. Apple Health via an iOS Shortcut) that need to hand
    the user a token to paste into an external tool. None for every other
    provider kind. MUST NOT be logged — repr is suppressed on this field
    specifically so it can never leak via a log line, an exception
    message, or an error-tracking breadcrumb that dumps the dataclass.
    """

    integration_id: str
    redirect_url: str | None = None
    ingest_token: str | None = field(default=None, repr=False)


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
