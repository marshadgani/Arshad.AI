"""add GIN index on ingested_obsidian_notes.tags

Revision ID: n1k2l3m4a5b6
Revises: m1j2k3l4a5b6
Create Date: 2026-09-14 00:00:00.000000

/api/v1/obsidian/notes filters with `tags @> '["<tag>"]'` (one clause per
requested tag, ANDed together) but the table only had btree indexes on
(user_id, github_path) and (user_id, last_modified_at) — neither supports
a JSONB containment lookup. Without this index, tag filtering falls back
to evaluating `@>` row-by-row over every note already matched by the
user_id predicate, which gets linearly slower as a vault grows.
jsonb_path_ops (rather than the default jsonb_ops) is used because the
only operator exercised against `tags` is `@>` — it produces a smaller,
faster index than jsonb_ops at the cost of not supporting `?`/`?|`/`?&`,
which this codebase never uses against this column.

Never edit an existing migration.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "n1k2l3m4a5b6"
down_revision: Union[str, None] = "m1j2k3l4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_obsidian_notes_tags_gin ON ingested_obsidian_notes "
        "USING GIN (tags jsonb_path_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_obsidian_notes_tags_gin", table_name="ingested_obsidian_notes")
