"""DagTriggerQueue — agents INSERT, workers poll-and-claim.

Worker contract: SELECT ... WHERE status='pending' ORDER BY requested_at
LIMIT 1 FOR UPDATE SKIP LOCKED. Both Airflow sensor (local docker-compose)
and the in-process FastAPI worker (Render prod) consume the same table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DagTriggerQueue(Base):
    __tablename__ = "dag_trigger_queue"
    __table_args__ = (
        Index("ix_dag_trigger_queue_status_requested_at", "status", "requested_at"),
        Index(
            "ix_dag_trigger_queue_user_id_requested_at",
            "user_id",
            "requested_at",
        ),
        # The dedupe check in _shared.py.make_sync_via_dag and the poll query
        # in routers.py.sync_job_status both filter on (user_id, dag_id) —
        # neither existing index above includes dag_id, so both queries fall
        # back to scanning every row for the user. This covers both.
        Index(
            "ix_dag_trigger_queue_user_id_dag_id_requested_at",
            "user_id",
            "dag_id",
            "requested_at",
        ),
        # Hard safety net for the TOCTOU race in make_sync_via_dag: a
        # SELECT ... FOR UPDATE only locks rows that already exist, so two
        # concurrent "Sync now" requests that both see no pending row can
        # both proceed to INSERT, producing duplicate queued jobs for the
        # same (user, dag). This partial unique index makes the second
        # concurrent INSERT fail at the database instead, and the app
        # catches that IntegrityError and folds it into the dedupe path.
        Index(
            "uq_dag_trigger_queue_pending_user_dag",
            "user_id",
            "dag_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dag_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | picked | completed | failed
    requested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
    picked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
