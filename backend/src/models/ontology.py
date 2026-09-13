"""Obsidian ontology layer — push-sync entity tracking.

``OntologyEntityNote`` maps a real-world entity (a Person, a Calendar
Event, a Gmail Thread, a GitHub Repo/IssuePR, or a domain MOC) to a
single note in the vault, keyed by a stable identity independent of the
file path. ``vault_path`` may change (renames); ``stable_entity_id``
never does — that split is what lets FEAT-141 resolve the same
real-world entity to the same note across every sync run.

``OntologySyncRun`` is the audit trail for each push-sync execution
(counts, commit SHA, status) — the natural home for facts that don't
belong on any single entity row, e.g. the vault commit a whole batch of
entities landed in.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    # Every column here is TIMESTAMP(timezone=True); a naive
    # datetime.utcnow() default stores fine but is inconsistent with the
    # timezone-aware datetimes the rest of this feature uses
    # (ontology/pipeline.py, ontology/resolve.py), and naive/aware raise
    # TypeError the moment anything tries to compare or subtract them.
    return datetime.now(timezone.utc)


class OntologyEntityNote(Base):
    __tablename__ = "ontology_entity_notes"
    __table_args__ = (
        UniqueConstraint("user_id", "stable_entity_id", name="uq_ontology_user_entity"),
        UniqueConstraint("user_id", "vault_path", name="uq_ontology_user_path"),
        Index("ix_ontology_user_domain_type", "user_id", "domain", "entity_type"),
        Index("ix_ontology_user_sync_state", "user_id", "sync_state"),
        Index("ix_ontology_user_seen", "user_id", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # calendar | email | github | people
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    # String, not a DB enum — a new entity type needs a new renderer,
    # never a migration. Person | Thread | Event | Repo | IssuePR | MOC.
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Logical identity, never changes across syncs. See resolve.py for
    # the exact derivation per entity type.
    stable_entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Always under ONTOLOGY_VAULT_ROOT. Mutable on rename.
    vault_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # Git blob SHA of the content WE last committed — sha1(b"blob N\0"+bytes),
    # computed locally. Drives the zero-network-call idempotent skip.
    blob_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    frontmatter_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    relationships: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # pending | synced | deferred | conflict | archived
    sync_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # foreign_path | drifted | tail_fetch_capped | rate_limit | concurrent_write
    conflict_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    missed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # DB-only. NEVER written into note content — that would change the
    # blob SHA on every run and destroy the idempotent-skip guarantee.
    last_synced_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class OntologySyncRun(Base):
    __tablename__ = "ontology_sync_runs"
    __table_args__ = (Index("ix_ontology_runs_user_started", "user_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # running | succeeded | partial | deferred | failed | dry_run
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dry_run: Mapped[bool] = mapped_column(nullable=False, default=False)
