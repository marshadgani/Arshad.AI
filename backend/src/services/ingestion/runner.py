"""ingestion_runner — single dispatch point shared by Airflow + queue worker.

Both the Airflow DAG (local docker-compose) and the in-process queue
worker (Render prod) call ``run(dag_id, user_id, payload, db)``. Per-DAG
logic lives in sibling modules (calendar.py, email.py, github.py,
analytics.py) so this file stays a thin switch.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from .dag_map import dag_to_slug

_log = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised when a runner can't proceed for a known reason.

    The queue worker treats this as a 'failed' status (after retry cap);
    the Airflow DAG fails the task. The error_text on dag_trigger_queue
    is set to ``f"{type(exc).__name__}: {exc}"``.
    """


async def _mark_integration_synced(
    *, user_id: uuid.UUID, dag_id: str, error: str | None
) -> None:
    """The single write site for integrations.last_synced_at/last_error
    for every queue/DAG-backed provider (FEAT-144).

    Opens its OWN session and commits explicitly rather than reusing the
    caller's `db`:
      - on the success path, the caller (a per-DAG ingest function) may
        commit conditionally (e.g. only `if rows:`) or not commit at all —
        reusing that session risks this write being silently rolled back
        on a legitimate zero-row sync, which would reproduce the original
        "false success" bug in a new place.
      - on the failure path, the caller's session is mid-rollback from the
        exception that got us here, so it cannot be reused at all.
    A missing/unmapped slug or a missing Integration row is a silent
    no-op — not every dag_id corresponds to a user-facing integration
    (e.g. analytics_processor).
    """
    slug = dag_to_slug(dag_id)
    if slug is None:
        return

    # Imported here, not at module scope, because models/database.py raises
    # at import time when DATABASE_URL is unset. The Airflow scheduler parses
    # data-pipelines/ingestion/*_dag.py without database credentials, and those
    # DAG files reach this module; a module-level import would turn DAG parsing
    # into an import error. Tests patch src.models.database.AsyncSessionLocal
    # (the source module), which works because this line re-reads the attribute
    # on every call. Do not hoist.
    from ...models.database import AsyncSessionLocal
    from ...models.integration import Integration

    async with AsyncSessionLocal() as session:
        integration = await session.scalar(
            select(Integration).where(
                Integration.user_id == user_id, Integration.slug == slug
            )
        )
        if integration is None:
            _log.debug(
                "no Integration row for user=%s slug=%s — skipping sync-status write",
                user_id,
                slug,
            )
            return
        integration.last_error = error
        if error is None:
            integration.last_synced_at = datetime.now(timezone.utc)
        await session.commit()


async def run(
    *,
    dag_id: str,
    user_id: uuid.UUID,
    payload: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise IngestionError(f"user_not_found: {user_id}")

    try:
        result = await _dispatch(dag_id=dag_id, user=user, db=db, payload=payload)
    except Exception as exc:
        await _mark_integration_synced(
            user_id=user_id, dag_id=dag_id, error=f"{type(exc).__name__}: {exc}"
        )
        raise
    await _mark_integration_synced(user_id=user_id, dag_id=dag_id, error=None)
    return result


async def _dispatch(
    *, dag_id: str, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    # Lazy imports avoid pulling Phase D / Phase F clients into modules
    # that only need the runner contract.
    if dag_id == "calendar_ingestor":
        from . import calendar as calendar_runner

        return await calendar_runner.ingest(user=user, db=db, payload=payload)
    if dag_id == "email_ingestor":
        from . import email as email_runner

        return await email_runner.ingest(user=user, db=db, payload=payload)
    if dag_id == "github_ingestor":
        from . import github as github_runner

        return await github_runner.ingest(user=user, db=db, payload=payload)
    if dag_id == "analytics_processor":
        from . import analytics as analytics_runner

        return await analytics_runner.compute(user=user, db=db, payload=payload)
    if dag_id == "obsidian_ingestor":
        from . import obsidian as obsidian_runner

        return await obsidian_runner.ingest(user=user, db=db, payload=payload)

    raise IngestionError(f"unknown_dag_id: {dag_id}")
