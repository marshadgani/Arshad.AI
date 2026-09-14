"""DagTriggerQueue — agents INSERT, workers poll-and-claim.

Worker contract: SELECT ... WHERE status='pending' ORDER BY requested_at
LIMIT 1 FOR UPDATE SKIP LOCKED. Both Airflow sensor (local docker-compose)
and the in-process FastAPI worker (Render prod) consume the same table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
        # FEAT-144: the dedup SELECT in _shared.py.make_sync_via_dag filters
        # on (user_id, dag_id, status) — neither index above has dag_id as a
        # column, so that lookup falls back to scanning every row for the
        # user via ix_dag_trigger_queue_user_id_requested_at and filtering
        # dag_id/status afterwards. This composite index makes it an index-only
        # lookup and also backs the (user_id, dag_id) fallback query in
        # routers.sync_job_status.
        Index(
            "ix_dag_trigger_queue_user_id_dag_id_requested_at",
            "user_id",
            "dag_id",
            "requested_at",
        ),
        # FEAT-144: closes a TOCTOU race in make_sync_via_dag — the dedup
        # SELECT and the subsequent INSERT are two separate statements, so
        # two concurrent sync requests (double-click, or a client retry
        # racing the first request) can both pass the "no job in flight"
        # check before either commits, enqueueing two DagTriggerQueue rows
        # and triggering the provider API twice — precisely the bug the
        # dedup check exists to prevent. A partial unique index makes the
        # second concurrent INSERT fail with IntegrityError instead of
        # silently succeeding; _sync() catches it and returns the winning
        # row's job_id (see personal/_shared.py). Scoped to pending/picked
        # only, so completed/failed history rows are never constrained.
        Index(
            "uq_dag_trigger_queue_user_dag_inflight",
            "user_id",
            "dag_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'picked')"),
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
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    picked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
