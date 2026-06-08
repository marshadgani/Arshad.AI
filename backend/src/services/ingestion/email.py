"""Gmail thread ingestion runner.

Pulls a window of threads via gmail_search_threads, upserts metadata into
ingested_gmail_threads keyed by (user_id, provider_id=thread_id). Body
content is NOT fetched here — gmail_get_thread is the heavy call and
should be on-demand. The ingestion stores the snippet + thread id so
later searches don't need to re-hit Gmail's list endpoint.

Window: ``in:inbox newer_than:30d`` by default. ``full_refresh=true``
widens to ``newer_than:1y``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.ingested import IngestedGmailThread
from ...models.user import User
from ...tools.gmail.search_threads import GmailSearchThreads, SearchThreadsInput
from .. import event_bus


def _max_batch() -> int:
    try:
        return max(1, int(os.getenv("MAX_INGEST_BATCH_SIZE", "100")))
    except ValueError:
        return 100


async def ingest(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    full_refresh = bool(payload.get("full_refresh", False))
    query = "in:inbox newer_than:1y" if full_refresh else "in:inbox newer_than:30d"

    result = await GmailSearchThreads()(
        user=user,
        db=db,
        payload=SearchThreadsInput(query=query, max_results=_max_batch()),
    )
    threads: list[dict[str, Any]] = (result.data or {}).get("threads", [])

    now = datetime.now(timezone.utc)
    rows = [
        {
            "user_id": user.id,
            # Gmail's threads.list doesn't return a date; ingest at runtime
            # and let downstream ingestion of gmail_get_thread refine.
            "occurred_at": now,
            "provider_id": thread["id"],
            "raw": thread,
        }
        for thread in threads
        if thread.get("id")
    ]
    skipped = len(threads) - len(rows)

    if rows:
        stmt = pg_insert(IngestedGmailThread).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "provider_id"],
            set_={"raw": stmt.excluded.raw, "ingested_at": now},
        )
        await db.execute(stmt)
        await db.commit()

    await event_bus.publish(
        "events.email.ingested",
        {
            "user_id": str(user.id),
            "ingested_count": len(rows),
            "skipped_count": skipped,
        },
    )
    return {"ingested_count": len(rows), "skipped_count": skipped}
