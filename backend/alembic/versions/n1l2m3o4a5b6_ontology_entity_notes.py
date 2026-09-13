"""ontology entity notes

Revision ID: n1l2m3o4a5b6
Revises: m1j2k3l4a5b6
Create Date: 2026-09-13 00:00:00.000000

FEAT-141 — Obsidian Ontology Layer. Adds the two tables backing the
push-sync direction (Postgres -> vault): ``ontology_entity_notes`` maps
a stable real-world-entity identity to its vault note (path may be
renamed; the identity never is), and ``ontology_sync_runs`` is the
per-run audit trail (commit SHA, counts, status).

``uq_ontology_user_path`` is DEFERRABLE INITIALLY DEFERRED — a rename
cycle (A takes B's old path, B takes C's) is only valid at the *end* of
a transaction, not at every intermediate UPDATE. Autogenerate does not
emit the deferrable clause; it is hand-added here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "n1l2m3o4a5b6"
down_revision: Union[str, None] = "m1j2k3l4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ontology_entity_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("stable_entity_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("vault_path", sa.String(length=500), nullable=False),
        sa.Column("blob_sha", sa.String(length=40), nullable=False, server_default=""),
        sa.Column(
            "frontmatter_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "relationships",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "sync_state", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("conflict_reason", sa.String(length=50), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missed_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ontology_entity_notes"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ontology_entity_notes_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "stable_entity_id", name="uq_ontology_user_entity"
        ),
        sa.UniqueConstraint(
            "user_id",
            "vault_path",
            name="uq_ontology_user_path",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        "ix_ontology_user_domain_type",
        "ontology_entity_notes",
        ["user_id", "domain", "entity_type"],
    )
    op.create_index(
        "ix_ontology_user_sync_state",
        "ontology_entity_notes",
        ["user_id", "sync_state"],
    )
    op.create_index(
        "ix_ontology_user_seen", "ontology_entity_notes", ["user_id", "last_seen_at"]
    )

    op.create_table(
        "ontology_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="running"
        ),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("branch", sa.String(length=200), nullable=True),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name="pk_ontology_sync_runs"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ontology_sync_runs_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_ontology_runs_user_started",
        "ontology_sync_runs",
        ["user_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ontology_runs_user_started", table_name="ontology_sync_runs")
    op.drop_table("ontology_sync_runs")
    op.drop_index("ix_ontology_user_seen", table_name="ontology_entity_notes")
    op.drop_index("ix_ontology_user_sync_state", table_name="ontology_entity_notes")
    op.drop_index("ix_ontology_user_domain_type", table_name="ontology_entity_notes")
    op.drop_table("ontology_entity_notes")
