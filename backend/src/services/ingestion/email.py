"""Gmail thread ingestion runner.

Three sequential phases (never ``asyncio.gather`` — ``AsyncSession`` is not
concurrency-safe and ``gmail.request`` performs a DB read plus a
``FOR UPDATE`` token refresh write on 401):

1. Fetch — inbox query always runs and its failure re-raises (it's the
   ingest's reason to exist). The starred/important queries each run in
   their own try/except; either one failing degrades to "no flagged
   threads found" without aborting the inbox ingest.
2. Dedup — results are merged into a dict keyed by ``thread['id']`` so a
   thread appearing in more than one query is upserted exactly once
   (this dict is the CardinalityViolation guard for the upsert below —
   do not replace it with a list). Derived label sets are unioned under
   the namespaced ``raw['_derived']['labels']`` key; no provider field is
   ever forged.
3. Enrichment — the flagged subset (non-empty ``_derived.labels``) gets a
   bounded number of sequential ``get_thread_metadata`` calls to recover
   the real subject/date, since Gmail's ``threads.list`` only returns
   ``{id, snippet, historyId}``. A per-thread failure degrades only that
   row (snippet + ingest-time stand in); it never aborts the batch.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.ingested import IngestedGmailThread
from ...models.user import User
from ...tools.base import ProviderNotLinked, ProviderReauthRequired
from ...tools.gmail.get_thread import get_thread_metadata
from ...tools.gmail.search_threads import GmailSearchThreads, SearchThreadsInput
from .. import event_bus
from .config import max_batch_size
from .runner import IngestionError

logger = logging.getLogger(__name__)


def _max_enrich_cap() -> int:
    try:
        return max(0, int(os.getenv("MAX_INGEST_ENRICH_CAP", "25")))
    except ValueError:
        return 25


async def _search(
    user: User, db: AsyncSession, query: str, cap: int
) -> list[dict[str, Any]]:
    result = await GmailSearchThreads()(
        user=user,
        db=db,
        payload=SearchThreadsInput(query=query, max_results=cap),
    )
    return (result.data or {}).get("threads", [])


async def ingest(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    full_refresh = bool(payload.get("full_refresh", False))
    window = "1y" if full_refresh else "30d"
    cap = max_batch_size()

    # Phase 1: fetch — inbox is load-bearing, flags are best-effort.
    inbox_threads = await _search(user, db, f"in:inbox newer_than:{window}", cap)

    degraded_queries: list[str] = []
    flag_queries = {
        "starred": f"in:inbox is:starred newer_than:{window}",
        "important": f"in:inbox is:important newer_than:{window}",
    }
    flag_results: dict[str, list[dict[str, Any]]] = {}
    for label, query in flag_queries.items():
        try:
            flag_results[label] = await _search(user, db, query, cap)
        except Exception as exc:  # noqa: BLE001 — degrade, don't abort
            logger.warning(
                "Gmail %s query failed (%s); no flagged threads found", label, exc
            )
            degraded_queries.append(label)
            flag_results[label] = []

    if len(degraded_queries) == len(flag_queries) and not inbox_threads:
        raise IngestionError(
            "gmail_all_queries_failed: inbox and flag queries all empty/failed"
        )

    # Phase 2: dedup — THIS DICT IS THE CardinalityViolation GUARD.
    # pg_insert(...).values() with two rows sharing (user_id, provider_id)
    # raises 21000. Do not replace with a list.
    merged: dict[str, dict[str, Any]] = {}
    total_fetched = 0
    for thread in inbox_threads:
        total_fetched += 1
        tid = thread.get("id")
        if not tid:
            continue
        merged.setdefault(tid, {**thread, "_labels": set()})

    for label, threads in flag_results.items():
        for thread in threads:
            total_fetched += 1
            tid = thread.get("id")
            if not tid:
                continue
            entry = merged.setdefault(tid, {**thread, "_labels": set()})
            entry["_labels"].add(label.upper())

    logger.debug(
        "Gmail ingest dedup: %d fetched -> %d unique threads",
        total_fetched,
        len(merged),
    )

    now = datetime.now(timezone.utc)
    future_clamp = now + timedelta(minutes=5)

    # Phase 3: bounded sequential enrichment of the flagged subset.
    flagged_ids = [tid for tid, t in merged.items() if t["_labels"]]
    enrich_budget = min(_max_enrich_cap(), len(flagged_ids))
    enriched_count = 0
    enrichment_failures = 0

    for tid in flagged_ids[:enrich_budget]:
        try:
            subject, date_header = await get_thread_metadata(
                user=user, db=db, thread_id=tid
            )
        except (ProviderReauthRequired, ProviderNotLinked):
            logger.warning("Gmail enrichment aborted: provider auth unavailable")
            break
        except Exception as exc:  # noqa: BLE001 — degrade this row only
            logger.warning("Gmail enrichment failed for thread %s (%s)", tid, exc)
            enrichment_failures += 1
            continue

        entry = merged[tid]
        if subject:
            entry["_subject"] = subject
        if date_header:
            entry["_date"] = date_header
            try:
                parsed = parsedate_to_datetime(date_header)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                entry["_occurred_at"] = min(parsed, future_clamp)
            except (TypeError, ValueError):
                pass
        enriched_count += 1

    rows = []
    for tid, thread in merged.items():
        derived: dict[str, Any] = {"labels": sorted(thread["_labels"])}
        if thread.get("_subject"):
            derived["subject"] = thread["_subject"]
        if thread.get("_date"):
            derived["date"] = thread["_date"]

        raw = {k: v for k, v in thread.items() if not k.startswith("_")}
        raw["_derived"] = derived

        rows.append(
            {
                "user_id": user.id,
                "occurred_at": thread.get("_occurred_at", now),
                "provider_id": tid,
                "raw": raw,
            }
        )

    skipped = total_fetched - len(rows)

    if rows:
        stmt = pg_insert(IngestedGmailThread).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "provider_id"],
            set_={
                "raw": stmt.excluded.raw,
                "occurred_at": stmt.excluded.occurred_at,
                "ingested_at": now,
            },
        )
        await db.execute(stmt)
        await db.commit()

    await event_bus.publish(
        "events.email.ingested",
        {
            "user_id": str(user.id),
            "ingested_count": len(rows),
            "skipped_count": skipped,
            "enriched_count": enriched_count,
            "enrichment_failures": enrichment_failures,
            "degraded_queries": degraded_queries,
        },
    )
    return {
        "ingested_count": len(rows),
        "skipped_count": skipped,
        "enriched_count": enriched_count,
        "enrichment_failures": enrichment_failures,
        "degraded_queries": degraded_queries,
    }
