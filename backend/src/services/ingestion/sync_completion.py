"""sync_completion — the ONLY writer of Integration.last_synced_at and
Integration.last_error for DAG-backed syncs (FEAT-144).

Called exactly once, from services/ingestion/runner.run()'s try/except/else
wrapper — the single dispatch point shared by both drainers (Render's
in-process queue worker and docker-compose's Airflow sensor). Neither
drainer touches Integration directly, so there is exactly one writer for
these two facts regardless of which drainer processed the row.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ...integrations.registry import slug_for_dag_id
from ...models.database import AsyncSessionLocal
from ...models.integration import Integration

_log = logging.getLogger(__name__)


async def finalize_sync(
    *, dag_id: str, user_id: uuid.UUID, success: bool, error_text: str | None
) -> None:
    """Best-effort completion bookkeeping.

    Opens its OWN committing session — independent of whatever session the
    caller (runner.run) used for the actual ingestion — so this write
    lands even if the caller's session is short-lived or already closed.
    Wrapped in a blanket try/except so a bookkeeping failure can NEVER turn
    a real ingestion success into a reported failure, or vice versa; the
    exception this function might raise is swallowed and logged, not
    propagated.
    """
    slug = slug_for_dag_id(dag_id)
    if slug is None:
        # e.g. analytics_processor, which has no per-user Integration row.
        return
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                integration = await db.scalar(
                    select(Integration).where(
                        Integration.user_id == user_id, Integration.slug == slug
                    )
                )
                if integration is None:
                    _log.warning(
                        "finalize_sync: no Integration row for user_id=%s slug=%s "
                        "(dag_id=%s) — skipping bookkeeping",
                        user_id,
                        slug,
                        dag_id,
                    )
                    return
                if success:
                    integration.last_synced_at = datetime.now(timezone.utc)
                    integration.last_error = None
                else:
                    integration.last_error = error_text
    except Exception:  # noqa: BLE001 — bookkeeping must never mask a real result
        _log.warning(
            "finalize_sync failed dag_id=%s user_id=%s success=%s",
            dag_id,
            user_id,
            success,
            exc_info=True,
        )
