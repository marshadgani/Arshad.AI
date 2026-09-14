"""Obsidian outbound export bookkeeping.

Two tables, deliberately separate from ``ingested_obsidian_notes``
(models/obsidian.py) so the inbound sync (vault -> Postgres) and the
outbound export (Postgres -> vault) never contend on the same rows:

- ``obsidian_export_state`` — one row per (user, domain) watermark.
- ``obsidian_exported_notes`` — a ledger of every note this backend has
  written, keyed by vault path, with a sha256 content hash used to skip
  re-writing unchanged notes. ``content_hash`` is deliberately 64 chars
  (sha256 hex) — distinct from ``ingested_obsidian_notes.blob_sha``
  (40-char git SHA-1) so the two can never be confused or compared.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ObsidianExportState(Base):
    __tablename__ = "obsidian_export_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "domain", name="uq_obsidian_export_state_user_domain"
        ),
        Index("ix_obsidian_export_state_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # calendar|email|github
    # Watermark over the source table's `ingested_at` column (NOT
    # occurred_at) — a backfilled/edited row gets a fresh ingested_at even
    # if its occurred_at is old, so this is the column that must never
    # regress on re-export.
    last_exported_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # Second half of the (ingested_at, id) keyset — same-millisecond rows
    # are never skipped or double-exported.
    last_exported_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # database.md: timestamps are set by the DB clock (func.now()), never a
    # naive Python datetime — datetime.utcnow() is tz-naive and would be
    # re-interpreted as local time on the way into a timestamptz column.
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ObsidianExportedNote(Base):
    """Ledger of notes this backend has written into the vault.

    Distinct from ``ingested_obsidian_notes`` on purpose (see module
    docstring) — the inbound ingestor excludes the ``Arshad.AI/`` prefix
    entirely, so a row here is never mirrored there.
    """

    __tablename__ = "obsidian_exported_notes"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "github_path", name="uq_obsidian_exported_user_path"
        ),
        Index(
            "ix_obsidian_exported_user_source",
            "user_id",
            "source_table",
            "source_row_id",
        ),
        Index("ix_obsidian_exported_user_domain", "user_id", "domain"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    github_path: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    source_table: Mapped[str] = mapped_column(String(50), nullable=False)
    source_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # sha256 hex of the rendered markdown — the hash gate. 64 chars, never
    # to be compared against a git blob SHA (40 chars, see module docstring).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Debugging only — never used for gating.
    blob_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    exported_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = ["ObsidianExportState", "ObsidianExportedNote"]
