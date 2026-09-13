"""Persistence for ingested GitHub activity.

The only module in the GitHub ingest path that names
``IngestedGitHubActivity`` or the Postgres dialect. Keeping the upsert
here means the orchestrator can be read as "fetch, map, write, account"
without the reader having to hold the conflict target and the updated
column set in their head, and means the unique-constraint contract has
exactly one definition site to keep in step with the model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.ingested import IngestedGitHubActivity

# Mirrors UniqueConstraint uq_ingested_github_user_kind_provider. `kind`
# is part of the key so issue#3 and pr#3 in the same repo are distinct
# rows rather than each overwriting the other.
_CONFLICT_TARGET = ["user_id", "kind", "provider_id"]


async def upsert_activity_rows(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Upsert one repo's rows and commit.

    No network call happens in here, which is what keeps the write
    transaction short (per database.md: never hold a transaction open
    across a network call). Callers fetch first, then hand the finished
    rows over.

    Re-ingesting an unchanged item refreshes ``raw``, ``occurred_at`` and
    ``ingested_at`` rather than inserting a duplicate, which is what makes
    the run idempotent and what lets a terminal-state transition (a PR
    becoming merged) overwrite the stale ``raw`` in place.
    """
    if not rows:
        return

    stmt = pg_insert(IngestedGitHubActivity).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=_CONFLICT_TARGET,
        set_={
            "raw": stmt.excluded.raw,
            "occurred_at": stmt.excluded.occurred_at,
            "ingested_at": datetime.now(timezone.utc),
        },
    )
    await db.execute(stmt)
    await db.commit()
