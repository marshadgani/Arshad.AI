"""drop duplicate skill_registry index

Revision ID: p1m2n3o4a5b6
Revises: o1l2m3n4a5b6
Create Date: 2026-09-14 00:00:00.000000

k1h2i3j4a5b6 created a UNIQUE constraint on skill_registry.skill_name AND a
separate explicit btree index on the same column. Postgres already backs a
UNIQUE constraint with its own index, so ix_skill_registry_skill_name is a
pure duplicate — extra storage plus extra write/vacuum cost on every
skill_registry upsert, with zero query benefit. Drop it; the unique
constraint's index continues to serve every lookup on skill_name.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "p1m2n3o4a5b6"
down_revision: Union[str, None] = "o1l2m3n4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        "ix_skill_registry_skill_name",
        table_name="skill_registry",
        if_exists=True,
    )


def downgrade() -> None:
    op.create_index("ix_skill_registry_skill_name", "skill_registry", ["skill_name"])
