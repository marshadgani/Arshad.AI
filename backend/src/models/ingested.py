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
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


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
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # 'issue' | 'pr'
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
