"""Single site for all credential-table DML performed during disconnect.

Every statement here is a bulk DELETE/UPDATE — never ORM row-loading.
Adding a future credential table means one new statement here and nowhere
else in the integrations layer (integrations/base.py calls this module and
never touches these tables directly).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import (
    ApiKeyCredential,
    IntegrationIngestToken,
    IntegrationOAuthToken,
)


@dataclass(frozen=True)
class ScrubCounts:
    oauth_rows: int
    apikey_rows: int
    ingest_rows: int


async def scrub_credentials(
    *, integration_id: uuid.UUID, db: AsyncSession
) -> ScrubCounts:
    """Hard-delete OAuth/API-key credentials; soft-revoke ingest tokens.

    The ingest token (Apple Health, and any future push-style provider) is
    SOFT-revoked — revoked_at is stamped, the row is never deleted.
    services/apple_health/ingest_auth.py authenticates incoming pushes by
    hashing the presented token and looking up the row with
    revoked_at IS NULL; deleting the row instead would make that lookup
    miss in a way indistinguishable from "never connected", and it would
    destroy the audit trail of a token that was live. Do not "simplify"
    this UPDATE into a DELETE.

    Does NOT commit — the caller owns the transaction boundary so this
    scrub and the integration's status flip land in one atomic commit.
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
        .values(revoked_at=func.now())
    )
    return ScrubCounts(
        oauth_rows=oauth_result.rowcount or 0,
        apikey_rows=apikey_result.rowcount or 0,
        ingest_rows=ingest_result.rowcount or 0,
    )
