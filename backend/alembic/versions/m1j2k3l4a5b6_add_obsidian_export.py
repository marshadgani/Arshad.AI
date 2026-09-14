"""add obsidian export tables

Revision ID: m1j2k3l4a5b6
Revises: l1i2j3k4a5b6
Create Date: 2026-09-14 00:00:00.000000

Adds obsidian_export_state (per-domain watermark) and
obsidian_exported_notes (write ledger, hash-gated) for the outbound
Arshad.AI -> Obsidian-vault exporter (FEAT-143). Also adds composite
(user_id, ingested_at, id) indexes on the three ingested_* tables the
exporter reads from — the existing (user_id, occurred_at) indexes don't
cover the watermark predicate used here.

Never edit an existing migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "m1j2k3l4a5b6"
down_revision: Union[str, None] = "l1i2j3k4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "obsidian_export_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("last_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_exported_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("notes_written", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_obsidian_export_state_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_obsidian_export_state"),
        sa.UniqueConstraint(
            "user_id", "domain", name="uq_obsidian_export_state_user_domain"
        ),
    )
    op.create_index(
        "ix_obsidian_export_state_user_id", "obsidian_export_state", ["user_id"]
    )

    op.create_table(
        "obsidian_exported_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_path", sa.String(500), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("source_table", sa.String(50), nullable=False),
        sa.Column("source_row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("blob_sha", sa.String(40), nullable=False, server_default=""),
        sa.Column("commit_sha", sa.String(40), nullable=False, server_default=""),
        sa.Column(
            "exported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_obsidian_exported_notes_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_obsidian_exported_notes"),
        sa.UniqueConstraint(
            "user_id", "github_path", name="uq_obsidian_exported_user_path"
        ),
    )
    op.create_index(
        "ix_obsidian_exported_user_source",
        "obsidian_exported_notes",
        ["user_id", "source_table", "source_row_id"],
    )
    op.create_index(
        "ix_obsidian_exported_user_domain",
        "obsidian_exported_notes",
        ["user_id", "domain"],
    )

    op.create_index(
        "ix_ingested_calendar_user_ingested",
        "ingested_calendar_events",
        ["user_id", "ingested_at", "id"],
    )
    op.create_index(
        "ix_ingested_gmail_user_ingested",
        "ingested_gmail_threads",
        ["user_id", "ingested_at", "id"],
    )
    op.create_index(
        "ix_ingested_github_user_ingested",
        "ingested_github_activity",
        ["user_id", "ingested_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingested_github_user_ingested", table_name="ingested_github_activity"
    )
    op.drop_index(
        "ix_ingested_gmail_user_ingested", table_name="ingested_gmail_threads"
    )
    op.drop_index(
        "ix_ingested_calendar_user_ingested", table_name="ingested_calendar_events"
    )
    op.drop_index(
        "ix_obsidian_exported_user_domain", table_name="obsidian_exported_notes"
    )
    op.drop_index(
        "ix_obsidian_exported_user_source", table_name="obsidian_exported_notes"
    )
    op.drop_table("obsidian_exported_notes")
    op.drop_index(
        "ix_obsidian_export_state_user_id", table_name="obsidian_export_state"
    )
    op.drop_table("obsidian_export_state")
