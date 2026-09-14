"""The integration disconnect workflow — types + orchestration (FEAT-145).

Extracted from IntegrationProvider (base.py) so that the provider ABC
declares *capabilities* ("can this provider revoke upstream, and how do I
get the payload for that call?") while this module owns the *workflow*
("prepare → close the read transaction → revoke → scrub + flip status
atomically → log").

Why the split:

- base.py is the contract every one of the ~44 providers inherits. Before
  this split it also imported ..services.integration_credentials and
  hand-rolled transaction management, which meant the abstract contract
  was coupled to a concrete persistence service and the only way to reuse
  the workflow was inheritance.
- The workflow has exactly one reason to change (how credential teardown
  is sequenced against the DB transaction and the network call); the
  provider contract has a different one (what a provider must implement).
  They now live in separate modules.
- Dependency direction is one-way: base.py → disconnect.py → services.
  disconnect.py imports nothing from base.py (the provider is accepted
  structurally, via RevocableProvider), so there is no import cycle and
  the workflow is unit-testable against any object with the two hooks.

Nothing in the sequencing changed in this extraction — see
backend/tests/test_integration_disconnect.py for the behaviour it pins.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import Integration
from ..services.integration_credentials import ScrubCounts, scrub_credentials

_log = logging.getLogger(__name__)


# 'revokes'    — the provider declares an upstream revoke call (revoke_url
#                or a hand-written _prepare_revocation/_revoke_upstream
#                override) that disconnect() will attempt.
# 'no_revoke'  — a real, provider-owned credential is stored locally, but
#                either the provider exposes no revocation endpoint or one
#                has not been verified/implemented yet. Local credentials
#                are still scrubbed — only the upstream call is skipped.
# 'no_credential' — this provider never stores a row in
#                integration_oauth_tokens/api_key_credentials to begin with
#                (e.g. Gmail/Calendar share the login-time Google grant in
#                oauth_accounts/oauth_tokens instead) — scrub_credentials()
#                is a provable no-op and there is nothing to revoke.
RevocationKind = Literal["revokes", "no_revoke", "no_credential"]

# What disconnect() actually attempted upstream, surfaced to the router
# response and the frontend's post-disconnect UI so a failed revoke is
# never presented as clean success.
UpstreamRevocationResult = Literal["revoked", "failed", "unsupported"]


@dataclass(frozen=True)
class DisconnectOutcome:
    status: Literal["disconnected"]
    upstream_revocation: UpstreamRevocationResult


class RevocableProvider(Protocol):
    """The slice of a provider this workflow actually uses.

    Structural, not nominal: run_disconnect() needs a slug for logging and
    the two revocation hooks — not the whole IntegrationProvider surface.
    Depending on the narrow shape is what keeps this module free of an
    import back into base.py.
    """

    slug: str

    async def _prepare_revocation(
        self, *, integration: Integration, db: AsyncSession
    ) -> Any | None: ...

    async def _revoke_upstream(self, *, payload: Any) -> UpstreamRevocationResult: ...


async def _attempt_upstream_revocation(
    provider: RevocableProvider, *, integration: Integration, payload: Any
) -> UpstreamRevocationResult:
    """Best-effort upstream revoke. A dead or slow third party must never
    block the user from disconnecting locally, so every failure is
    swallowed — but it is reported as 'failed' rather than silently
    presented as success.
    """
    try:
        return await provider._revoke_upstream(payload=payload)
    except Exception:  # noqa: BLE001 — a dead/slow provider must not block disconnect
        _log.warning(
            "Upstream revoke failed for %s (integration_id=%s)",
            provider.slug,
            integration.id,
            exc_info=True,
        )
        return "failed"


async def _scrub_and_mark_disconnected(
    *, integration: Integration, db: AsyncSession
) -> ScrubCounts:
    """Delete local credentials and flip the status in ONE transaction, so
    "credentials gone but status still connected" (or the reverse) is
    unrepresentable. Any failure rolls back both and propagates, leaving
    the integration exactly as it was.
    """
    try:
        counts = await scrub_credentials(db, integration_id=integration.id)
        integration.status = "disconnected"
        integration.last_error = None
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return counts


async def run_disconnect(
    provider: RevocableProvider, *, integration: Integration, db: AsyncSession
) -> DisconnectOutcome:
    """Revoke upstream where supported, then unconditionally scrub every
    locally stored credential row for this integration and mark it
    disconnected.

    Sequence, and why each step is ordered this way:
      1. _prepare_revocation() reads (and decrypts) whatever credential the
         network call needs, while the DB's read transaction is still open.
      2. That read transaction is committed/closed BEFORE any network call
         — never hold a transaction open across a network call
         (.claude/rules/database.md).
      3. The upstream revoke is attempted and swallowed on failure, but its
         outcome is reported so the caller can surface it.
      4. Local credential scrub + status flip commit together.
    """
    payload = await provider._prepare_revocation(integration=integration, db=db)
    if db.in_transaction():
        await db.commit()

    upstream_revocation: UpstreamRevocationResult = "unsupported"
    if payload is not None:
        upstream_revocation = await _attempt_upstream_revocation(
            provider, integration=integration, payload=payload
        )

    counts = await _scrub_and_mark_disconnected(integration=integration, db=db)
    _log.info(
        "integration.disconnect slug=%s integration_id=%s user_id=%s "
        "upstream_revocation=%s oauth_tokens_deleted=%s "
        "api_key_credentials_deleted=%s ingest_tokens_revoked=%s",
        provider.slug,
        integration.id,
        integration.user_id,
        upstream_revocation,
        counts.oauth_tokens_deleted,
        counts.api_key_credentials_deleted,
        counts.ingest_tokens_revoked,
    )
    return DisconnectOutcome(
        status="disconnected", upstream_revocation=upstream_revocation
    )
