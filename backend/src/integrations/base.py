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
from datetime import datetime, timezone
from typing import Any, ClassVar, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import Integration
from ..models.user import User
from ..services.integration_credentials import scrub_credentials
from ..utils.errors import LAST_ERROR_MAX_CHARS, error_summary, log_detail, safe_detail

__all__ = [
    "IntegrationError",
    "IntegrationKind",
    "IntegrationStatus",
    "RevocationKind",
    "UpstreamRevocationResult",
    "ConnectResult",
    "SyncResult",
    "StatusReport",
    "DisconnectOutcome",
    "IntegrationProvider",
    "LAST_ERROR_MAX_CHARS",
    "safe_detail",
    "log_detail",
    "error_summary",
]

IntegrationKind = Literal[
    "personal_oauth", "personal_apikey", "project_apikey", "static", "personal_push"
]
IntegrationStatus = Literal[
    "connected", "disconnected", "error", "expired", "coming_soon"
]

# Declared per-provider (ClassVar, no default — see IntegrationProvider.
# revocation_kind below) and used to drive the frontend's disconnect-dialog
# copy. Three honest shades of "what actually happens on disconnect":
#   revokes        — an upstream revoke call is attempted (real credential,
#                     a documented revoke endpoint exists)
#   no_revoke      — the local credential is deleted; no revoke endpoint is
#                     published, so nothing upstream can be told
#   no_credential  — this provider is a thin view over another provider's
#                     shared login grant; it never held a credential row of
#                     its own, so there is nothing local to remove either
RevocationKind = Literal["revokes", "no_revoke", "no_credential"]

# What _revoke_upstream() actually achieved. Advisory only — it is surfaced
# to the caller but never changes the local disconnect outcome: the user's
# "remove my stored credentials" action always succeeds locally regardless
# of whether the third party cooperated.
UpstreamRevocationResult = Literal["revoked", "failed", "unsupported"]

_log = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class DisconnectOutcome:
    """Returned by disconnect(). Advisory field only — the local disconnect
    (status flip + credential scrub) has already succeeded by the time this
    is constructed; the router never lets upstream_revocation change the
    HTTP status."""

    upstream_revocation: UpstreamRevocationResult


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

    # NO DEFAULT — deliberate. A provider that forgets to declare this is
    # caught by the registry-walk test (test_integrations_disconnect.py)
    # rather than silently inheriting a value that misrepresents what
    # disconnect() actually does for it.
    revocation_kind: ClassVar[RevocationKind]

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
        """Read + decrypt whatever _revoke_upstream needs, while the read
        transaction is still open. Default: nothing to revoke. Providers
        that own a real upstream credential (OAuthIntegrationProvider,
        Plaid) override this.

        A dict payload may carry a "_preserve" key — a dict merged
        verbatim into integration.config['last_disconnect'] after the
        scrub. This is how Plaid keeps a recoverable item_id around after
        its ApiKeyCredential row is deleted, without base.py needing any
        Plaid-specific knowledge.
        """
        return None

    async def _revoke_upstream(
        self, *, payload: Any | None
    ) -> UpstreamRevocationResult:
        """Call the provider's revoke endpoint. No `db` parameter — this is
        a structural guardrail, not a style choice: a subclass cannot
        reopen a transaction mid-network-call from inside this method.
        Default: no revoke endpoint is known, so 'unsupported'."""
        return "unsupported"

    async def disconnect(
        self, *, integration: Integration, db: AsyncSession
    ) -> DisconnectOutcome:
        """Revoke credentials upstream where supported, then scrub them
        locally. Mandatory four-step sequence (.claude/rules/database.md —
        never hold a transaction open across a network call):

          1. _prepare_revocation() while the read transaction is open.
          2. Commit + close that transaction BEFORE any network call.
          3. _revoke_upstream() with no db handle in scope. Every
             exception is caught and recorded as 'failed', never
             propagated — a user-initiated disconnect must not be blocked
             by a third party being unreachable.
          4. scrub_credentials() + status flip in ONE atomic commit. On
             commit failure: rollback and propagate — a visibly-failed
             disconnect the user can retry, never a half-scrubbed one.
        """
        try:
            payload = await self._prepare_revocation(integration=integration, db=db)
        except Exception:  # noqa: BLE001 — corrupt ciphertext etc. must not block the local scrub
            _log.warning(
                "disconnect: _prepare_revocation failed for %s (integration_id=%s)",
                self.slug,
                integration.id,
            )
            payload = None

        await db.commit()

        try:
            upstream_revocation = await self._revoke_upstream(payload=payload)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "disconnect: upstream revoke failed for %s (integration_id=%s): %s",
                self.slug,
                integration.id,
                type(exc).__name__,
            )
            upstream_revocation = "failed"

        preserve = payload.get("_preserve") if isinstance(payload, dict) else None

        counts = await scrub_credentials(integration_id=integration.id, db=db)
        integration.status = "disconnected"
        integration.last_error = None
        integration.config = {
            **(integration.config or {}),
            "last_disconnect": {
                "at": datetime.now(timezone.utc).isoformat(),
                "upstream_revocation": upstream_revocation,
                "scrub_counts": {
                    "oauth_rows": counts.oauth_rows,
                    "apikey_rows": counts.apikey_rows,
                    "ingest_rows": counts.ingest_rows,
                },
                **(preserve or {}),
            },
        }
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return DisconnectOutcome(upstream_revocation=upstream_revocation)
