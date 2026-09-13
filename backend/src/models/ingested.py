"""Ingested data tables — hybrid storage.

Each row keeps the provider's full response under ``raw`` (jsonb) plus
typed columns we'll definitely query (user_id, occurred_at, provider_id).
UNIQUE(user_id, provider_id) enables idempotent ON CONFLICT upserts so
re-running ingestion doesn't insert duplicates.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# The only two values ever written by the ingestion pipeline
# (backend/src/services/ingestion/github.py) and the only two values the
# dashboard endpoints filter on (/agent-activity queries kind='pr',
# /notifications queries kind='issue'). Previously this was a bare `str`
# with the invariant stated only in a trailing comment — nothing stopped a
# typo'd kind from silently vanishing from both dashboard widgets. The
# annotation below is static-only (mypy/pyright); the column stays
# String(20) at the DB layer so no migration is required, and any actual
# out-of-band value already in the table still loads fine at runtime.
GitHubActivityKind = Literal["issue", "pr"]

# "This Gmail thread carries at least one derived label" — the predicate of
# the partial index below AND the WHERE clause of
# ``services/dashboard/queries.fetch_flagged_gmail_threads``. Exported so
# both sides emit one identical string rather than two hand-synced copies.
#
# It must be literal SQL on the query side, not an ORM expression. Postgres
# only uses a partial index when the query's WHERE clause is *provably
# implied* by the index predicate, and that proof runs over the parsed
# expression tree, where a bind parameter is not equal to a constant. The
# natural ORM spelling (``Model.raw["_derived"]["labels"]``) compiles the
# JSON path keys to bind parameters — ``raw -> $2 -> $3`` — which the
# planner cannot prove equal to ``raw -> '_derived' -> 'labels'``. The
# proof then fails and the partial index is silently dropped in favour of
# a full (user_id, occurred_at) scan with a residual filter: same rows,
# same results, no error, just a steadily worsening scan as the unflagged
# majority of the mailbox grows.
#
# That degradation only materialises under a *generic* plan, which is why
# it does not show up in a quick EXPLAIN: with the default
# ``plan_cache_mode = auto`` Postgres re-plans with the parameters folded
# in for the first executions and happens to keep choosing the custom
# plan here. The correctness of the index therefore rested on a planner
# heuristic and a cost margin that shifts with data distribution. Emitting
# constants on both sides makes the index usable under either plan mode.
# Regression-tested in ``backend/tests/test_gmail_flagged_index.py``.
#
# Safe as literal SQL: a module constant with no interpolation and no
# user input. ``user_id`` stays a bound parameter at the call site.
GMAIL_FLAGGED_LABELS_PREDICATE = (
    "jsonb_typeof(raw->'_derived'->'labels') = 'array' "
    "AND jsonb_array_length(raw->'_derived'->'labels') > 0"
)


class IngestedCalendarEvent(Base):
    __tablename__ = "ingested_calendar_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider_id", name="uq_ingested_calendar_user_provider"
        ),
        Index("ix_ingested_calendar_user_occurred", "user_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )


class IngestedGmailThread(Base):
    __tablename__ = "ingested_gmail_threads"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider_id", name="uq_ingested_gmail_user_provider"
        ),
        Index("ix_ingested_gmail_user_occurred", "user_id", "occurred_at"),
        # Partial index serving the /api/v1/dashboard/tasks predicate, so
        # that JSONB filter is index-served instead of a post-scan filter
        # over every thread the user has. The predicate is not spelled out
        # here: it and the query's WHERE clause are the same constant, so
        # the two cannot drift apart. See GMAIL_FLAGGED_LABELS_PREDICATE.
        Index(
            "ix_ingested_gmail_flagged_user_occurred",
            "user_id",
            "occurred_at",
            postgresql_where=text(GMAIL_FLAGGED_LABELS_PREDICATE),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )


class IngestedGitHubActivity(Base):
    __tablename__ = "ingested_github_activity"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "kind",
            "provider_id",
            name="uq_ingested_github_user_kind_provider",
        ),
        Index("ix_ingested_github_user_occurred", "user_id", "occurred_at"),
        # Covers the (user_id, kind) equality filter used by both
        # /api/v1/dashboard/agent-activity (kind='pr') and
        # /api/v1/dashboard/notifications (kind='issue') so `kind` is an
        # index condition rather than a residual filter over rows of the
        # other kind.
        Index(
            "ix_ingested_github_user_kind_occurred",
            "user_id",
            "kind",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    kind: Mapped[GitHubActivityKind] = mapped_column(String(20), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )


class IngestedAnalyticsSummary(Base):
    __tablename__ = "ingested_analytics_summary"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "metric_key",
            "occurred_at",
            name="uq_ingested_analytics_user_metric_window",
        ),
        Index("ix_ingested_analytics_user_metric", "user_id", "metric_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
