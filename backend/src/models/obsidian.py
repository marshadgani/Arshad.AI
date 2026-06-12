"""Obsidian vault note storage.

Each row represents one .md file from the user's Obsidian vault GitHub repo.
UNIQUE(user_id, github_path) enables idempotent ON CONFLICT upserts so
re-running ingestion doesn't insert duplicates.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class IngestedObsidianNote(Base):
    __tablename__ = "ingested_obsidian_notes"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "github_path", name="uq_ingested_obsidian_user_path"
        ),
        Index("ix_ingested_obsidian_user_path", "user_id", "github_path"),
        Index("ix_ingested_obsidian_user_modified", "user_id", "last_modified_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Path relative to vault root, e.g. "Daily Notes/2026-06-12.md"
    github_path: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Parsed YAML frontmatter dict
    frontmatter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Extracted tag list (from frontmatter or inline #tags)
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # GitHub blob SHA — used to skip unchanged files on re-sync
    blob_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    last_modified_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
