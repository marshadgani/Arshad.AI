"""skill registry category+display_name composite index

Revision ID: n1k2l3m4a5b6
Revises: m1j2k3l4a5b6
Create Date: 2026-09-14 00:00:00.000000

Supports the ORDER BY category, display_name used by
GET /api/v1/ai-ecosystem/skills, and the category equality filter added in
the same feature (FEAT-154). Does NOT cover the free-text `q` search filter
(ILIKE '%...%' is unindexable without pg_trgm) — at ~1.3k rows a sequential
scan there is sub-millisecond; revisit only if skill_registry grows to
tens of thousands of rows.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "n1k2l3m4a5b6"
down_revision: Union[str, None] = "m1j2k3l4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_skill_registry_category_display_name",
        "skill_registry",
        ["category", "display_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_skill_registry_category_display_name", table_name="skill_registry"
    )
