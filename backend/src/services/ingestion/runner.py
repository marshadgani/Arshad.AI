"""ingestion_runner — single dispatch point shared by Airflow + queue worker.

Both the Airflow DAG (local docker-compose) and the in-process queue
worker (Render prod) call ``run(dag_id, user_id, payload, db)``. Per-DAG
logic lives in sibling modules (calendar.py, email.py, github.py,
analytics.py) so this file stays a thin switch.

TRANSACTION CONTRACT — EACH PER-DAG MODULE MUST COMMIT ITS OWN WRITES
------------------------------------------------------------------------
Neither caller commits the session it passes in. Both wrap the call in
``async with AsyncSessionLocal() as db:``, and ``AsyncSession.__aexit__``
closes the session, which ROLLS BACK any still-open transaction. A
per-DAG module that defers its commit to "the caller" therefore loses
every write silently while still reporting success, and the worker will
still mark the queue row ``completed``. Every module dispatched below
calls ``db.commit()`` itself — keep it that way when adding a new DAG.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from .errors import IngestionError  # noqa: F401 — re-exported for existing callers


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
    if dag_id == "ontology_extractor":
        from . import ontology_extract as ontology_extract_svc

        return await ontology_extract_svc.extract(user=user, db=db, payload=payload)

    raise IngestionError(f"unknown_dag_id: {dag_id}")
