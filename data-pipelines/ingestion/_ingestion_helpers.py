"""Shared helpers for Airflow ingestion DAGs.

Each of the 4 DAGs (calendar_dag, email_dag, github_dag, analytics_dag)
follows the same shape:

    sensor (claim_one) >> ingest (run_ingest_for_row) >> mark_done

The DAG's only customization is the ``dag_id`` string. All three tasks
delegate to functions here, which in turn call into the shared backend
runner at ``backend/src/services/ingestion/runner.py``.

Path note: this file lives in ``data-pipelines/ingestion/`` (where the
Airflow scheduler picks up DAGs) but imports from ``backend/src/...``.
The compose volume mounts both, so the import works inside the airflow
container as long as ``backend/`` is on PYTHONPATH (set in compose).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

# Make the backend package importable without a wheel install.
_BACKEND_PATH = os.environ.get("ARSHAD_BACKEND_PATH", "/opt/airflow/backend")
if _BACKEND_PATH not in sys.path:
    sys.path.insert(0, _BACKEND_PATH)

_log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def claim_one(*, dag_id: str, **_context) -> bool:
    """PythonSensor callback: returns True when a row was claimed.

    Pushes the claimed row's id (str) to XCom under key 'claimed_run_id'
    via the standard Airflow return value (whatever is returned becomes
    the XCom for the sensor task).
    """
    from sqlalchemy import select
    from src.models.dag_trigger import DagTriggerQueue
    from src.models.database import AsyncSessionLocal

    async def _do() -> str | None:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                row = await db.scalar(
                    select(DagTriggerQueue)
                    .where(
                        DagTriggerQueue.dag_id == dag_id,
                        DagTriggerQueue.status == "pending",
                    )
                    .order_by(DagTriggerQueue.requested_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if row is None:
                    return None
                row.status = "picked"
                row.picked_at = datetime.now(timezone.utc)
                row.attempt = (row.attempt or 0) + 1
                db.add(row)
            return str(row.id)

    claimed_id = _run(_do())
    if claimed_id is None:
        return False
    # Stash for downstream tasks via XCom side channel.
    os.environ[f"_ARSHAD_CLAIMED_{dag_id}"] = claimed_id
    _log.info("claimed run_id=%s for dag_id=%s", claimed_id, dag_id)
    return True


def _claimed_id(dag_id: str) -> uuid.UUID:
    raw = os.environ.get(f"_ARSHAD_CLAIMED_{dag_id}")
    if not raw:
        raise RuntimeError(f"no claimed run_id for dag_id={dag_id}")
    return uuid.UUID(raw)


def run_ingest_for_row(*, dag_id: str, **_context) -> None:
    """Calls the shared backend runner with the claimed row's payload."""
    from sqlalchemy import select
    from src.models.dag_trigger import DagTriggerQueue
    from src.models.database import AsyncSessionLocal
    from src.services.ingestion import runner as ingestion_runner

    run_id = _claimed_id(dag_id)

    async def _do() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(DagTriggerQueue).where(DagTriggerQueue.id == run_id)
            )
            if row is None:
                raise RuntimeError(f"run_id={run_id} disappeared after claim")
            return await ingestion_runner.run(
                dag_id=row.dag_id,
                user_id=row.user_id,
                payload=row.payload,
                db=db,
            )

    result = _run(_do())
    _log.info("ingest result run_id=%s result=%s", run_id, result)


def mark_done(*, dag_id: str, **context) -> None:
    """Sets queue row status. Reads the upstream ingest task state to
    decide success vs. retry-or-fail."""
    from sqlalchemy import select
    from src.models.dag_trigger import DagTriggerQueue
    from src.models.database import AsyncSessionLocal

    run_id = _claimed_id(dag_id)
    ti = context["ti"]
    upstream_state = ti.xcom_pull(task_ids="run_ingest", key="return_value")
    upstream_failed = ti.get_dagrun().get_task_instance("run_ingest").state in (
        "failed",
        "upstream_failed",
    )

    async def _do() -> None:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                row = await db.scalar(
                    select(DagTriggerQueue).where(DagTriggerQueue.id == run_id)
                )
                if row is None:
                    return
                if upstream_failed:
                    if row.attempt >= _MAX_ATTEMPTS:
                        row.status = "failed"
                        row.completed_at = datetime.now(timezone.utc)
                    else:
                        row.status = "pending"
                    if not row.error_text:
                        row.error_text = "ingest task failed"
                else:
                    row.status = "completed"
                    row.completed_at = datetime.now(timezone.utc)
                    row.error_text = None
                db.add(row)

    _run(_do())
    os.environ.pop(f"_ARSHAD_CLAIMED_{dag_id}", None)
    _log.info("mark_done run_id=%s upstream_failed=%s", run_id, upstream_failed)
