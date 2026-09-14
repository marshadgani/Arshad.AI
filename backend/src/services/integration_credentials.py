"""Where integration credential material lives, and how each kind is scrubbed.

Two facts live here and nowhere else: *which* tables hold credential
material for an integration, and *how* each of them is cleared —
hard-delete where the row IS the secret, soft-revoke where the row is
only a hash and doubles as an audit record.

Both were previously restated in `IntegrationProvider.disconnect()` and
again in `scripts/scrub_orphaned_integration_credentials.py`. Two copies
of a security policy is one too many: a table added to one and not the
other silently leaves a live credential behind, which is the exact bug
the disconnect fix exists to clean up after.

What deliberately does NOT live here:

  - **Transaction control.** Nothing here commits or rolls back. Only the
    caller knows what else must land atomically with the scrub —
    disconnect() flips `Integration.status` in the same transaction; the
    remediation script commits one bulk sweep.
  - **Upstream revocation.** Telling the third party to stop trusting a
    credential is a per-provider network concern — see
    `IntegrationProvider._revoke_upstream()`.
  - **`oauth_accounts` / `oauth_tokens`.** The shared Arshad.AI login
    grant is not integration credential material. It has no
    `integration_id` column, so no statement built here can reach it, and
    disconnecting a Google/GitHub *integration* must never sign the user
    out of Arshad.AI itself.

It lives under `services/` rather than `integrations/` because importing
`src.integrations` pulls in every provider module (that package's
`__init__` populates INTEGRATION_REGISTRY and needs REDIS_URL et al. just
to import). The remediation script needs the policy, not the registry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import (
    ApiKeyCredential,
    IntegrationIngestToken,
    IntegrationOAuthToken,
)

# Which integrations to act on: one specific integration (the disconnect
# path) or a subquery selecting many (the bulk remediation path). Both
# go through _scoped() below rather than hand-rolling a WHERE clause —
# the bug this guards against (a missing WHERE, clearing every user's
# credentials) is not one you get a second chance at.
CredentialScope = uuid.UUID | Select[Any]

# A token that has already been revoked is not live: excluded so a re-run
# neither double-counts nor rewrites a historical revocation timestamp.
_LIVE_INGEST_TOKEN = IntegrationIngestToken.revoked_at.is_(None)


@dataclass(frozen=True)
class ScrubCounts:
    """Row counts per credential table, for logging and dry-run reporting.

    Never carries credential material — only how many rows were affected.
    """

    api_key_rows: int
    oauth_rows: int
    ingest_rows: int


def _scoped(model: type[Any], scope: CredentialScope) -> ColumnElement[bool]:
    column = model.integration_id
    return column == scope if isinstance(scope, uuid.UUID) else column.in_(scope)


async def _count(
    db: AsyncSession,
    model: type[Any],
    scope: CredentialScope,
    *extra: ColumnElement[bool],
) -> int:
    stmt = select(func.count()).select_from(model).where(_scoped(model, scope), *extra)
    return await db.scalar(stmt) or 0


async def _delete(db: AsyncSession, model: type[Any], scope: CredentialScope) -> int:
    """Hard-delete: the row IS the secret (an encrypted API key, an
    encrypted OAuth token bundle). Nothing is left worth keeping once it
    must stop working."""
    result = await db.execute(
        sa_delete(model)
        .where(_scoped(model, scope))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def _revoke_ingest_tokens(db: AsyncSession, scope: CredentialScope) -> int:
    """Soft-revoke: only a one-way hash is stored, so the row is useless
    to an attacker but still useful to us — stamped with `revoked_at` it
    records that a token existed and when it stopped authenticating."""
    result = await db.execute(
        sa_update(IntegrationIngestToken)
        .where(_scoped(IntegrationIngestToken, scope), _LIVE_INGEST_TOKEN)
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def count_live_credentials(
    db: AsyncSession, *, scope: CredentialScope
) -> ScrubCounts:
    """How many live credential rows `scrub_credentials` would affect.

    Read-only — the dry-run half of the remediation script, and usable as
    a post-condition assertion anywhere else.
    """
    return ScrubCounts(
        api_key_rows=await _count(db, ApiKeyCredential, scope),
        oauth_rows=await _count(db, IntegrationOAuthToken, scope),
        ingest_rows=await _count(db, IntegrationIngestToken, scope, _LIVE_INGEST_TOKEN),
    )


async def scrub_credentials(db: AsyncSession, *, scope: CredentialScope) -> ScrubCounts:
    """Clear every stored credential for the in-scope integration(s).

    Credentials granting third-party access go first, so a mid-sweep
    failure has done the most valuable work first. Does NOT commit — see
    the module docstring. Idempotent: a re-run against already-scrubbed
    integrations affects zero rows rather than erroring or re-stamping
    `revoked_at`.
    """
    return ScrubCounts(
        api_key_rows=await _delete(db, ApiKeyCredential, scope),
        oauth_rows=await _delete(db, IntegrationOAuthToken, scope),
        ingest_rows=await _revoke_ingest_tokens(db, scope),
    )
