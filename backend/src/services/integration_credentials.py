"""Sole implementation site for local integration-credential destruction.

FEAT-145: IntegrationProvider.disconnect()'s old default only flipped
integration.status — it never touched the encrypted OAuth/API-key rows
sitting in Postgres, a silent false promise against the frontend's
disconnect confirmation ("Stored credentials will be removed"). This is
the one place that promise is kept, for every provider kind.

Bulk DML only — no ORM row loading, no per-row Python-side work — because
disconnect() runs on a user-facing action path and adding a future
credential table should mean one new statement here, not auditing ~25
provider files for a missed override.

Never touches: integrations, oauth_accounts, oauth_tokens, or any
ingested_* table. The Integration row itself always survives a disconnect
so the UI can keep showing a disconnected card and the user can
reconnect later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import (
    ApiKeyCredential,
    IntegrationIngestToken,
    IntegrationOAuthToken,
)


@dataclass(frozen=True)
class ScrubCounts:
    oauth_tokens_deleted: int
    api_key_credentials_deleted: int
    ingest_tokens_revoked: int


async def scrub_credentials(
    db: AsyncSession, *, integration_id: uuid.UUID
) -> ScrubCounts:
    """Delete/revoke every locally-stored credential row for one integration.

    Runs inside the caller's existing transaction — never commits or rolls
    back itself; that's the caller's responsibility (see
    IntegrationProvider.disconnect()). Idempotent: calling this a second
    time for an already-scrubbed integration deletes/revokes zero rows
    rather than raising.
    """
    oauth_result = await db.execute(
        delete(IntegrationOAuthToken).where(
            IntegrationOAuthToken.integration_id == integration_id
        )
    )
    apikey_result = await db.execute(
        delete(ApiKeyCredential).where(
            ApiKeyCredential.integration_id == integration_id
        )
    )
    ingest_result = await db.execute(
        update(IntegrationIngestToken)
        .where(
            IntegrationIngestToken.integration_id == integration_id,
            IntegrationIngestToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return ScrubCounts(
        oauth_tokens_deleted=oauth_result.rowcount or 0,
        api_key_credentials_deleted=apikey_result.rowcount or 0,
        ingest_tokens_revoked=ingest_result.rowcount or 0,
    )
