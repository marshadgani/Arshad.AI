"""obsidian notes table

Revision ID: j1g2h3i4a5b6
Revises: i1f2g3h4a5b6
Create Date: 2026-06-12 12:00:00.000000

Adds ingested_obsidian_notes table for Obsidian vault sync via GitHub.
Full-text search index created at the end of upgrade() via raw SQL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "j1g2h3i4a5b6"
down_revision: Union[str, None] = "i1f2g3h4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingested_obsidian_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_path", sa.String(500), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "frontmatter",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("word_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blob_sha", sa.String(40), nullable=False, server_default=""),
        sa.Column(
            "last_modified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ingested_obsidian_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingested_obsidian_notes"),
        sa.UniqueConstraint(
            "user_id", "github_path", name="uq_ingested_obsidian_user_path"
        ),
    )
    op.create_index(
        "ix_ingested_obsidian_user_path",
        "ingested_obsidian_notes",
        ["user_id", "github_path"],
    )
    op.create_index(
        "ix_ingested_obsidian_user_modified",
        "ingested_obsidian_notes",
        ["user_id", "last_modified_at"],
    )
    # Full-text search GIN index on title + content
    op.execute(
        "CREATE INDEX ix_obsidian_notes_fts ON ingested_obsidian_notes "
        "USING GIN (to_tsvector('english', "
        "coalesce(title, '') || ' ' || coalesce(content, '')))"
    )

    # Add Obsidian nav item
    op.get_bind().execute(
        sa.text(
            "INSERT INTO nav_items (path, label, icon, domain, ord) "
            "VALUES (:path, :label, :icon, :domain, :ord) "
            "ON CONFLICT (path) DO UPDATE "
            "SET label = EXCLUDED.label, icon = EXCLUDED.icon, ord = EXCLUDED.ord"
        ),
        {
            "path": "/obsidian",
            "label": "Obsidian",
            "icon": "🔮",
            "domain": None,
            "ord": 9,
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM nav_items WHERE path = '/obsidian'"))
    op.drop_index("ix_obsidian_notes_fts", table_name="ingested_obsidian_notes")
    op.drop_index(
        "ix_ingested_obsidian_user_modified", table_name="ingested_obsidian_notes"
    )
    op.drop_index(
        "ix_ingested_obsidian_user_path", table_name="ingested_obsidian_notes"
    )
    op.drop_table("ingested_obsidian_notes")
