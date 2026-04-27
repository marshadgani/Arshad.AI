"""Integration parent model + ApiKeyCredential subtype.

Personal-OAuth integrations join to existing oauth_accounts via
(user_id, provider) — they don't get a direct FK to keep migrations
backwards-compatible with Phase C data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, TimestampedMixin


class Integration(Base, TimestampedMixin):
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_integrations_user_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="disconnected"
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ApiKeyCredential(Base, TimestampedMixin):
    __tablename__ = "api_key_credentials"
    __table_args__ = (
        UniqueConstraint("integration_id", name="uq_apikey_one_per_integration"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    encrypted_key: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
