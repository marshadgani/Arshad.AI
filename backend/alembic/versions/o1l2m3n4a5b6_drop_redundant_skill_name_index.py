"""drop redundant skill_registry.skill_name index

Revision ID: o1l2m3n4a5b6
Revises: n1k2l3m4a5b6
Create Date: 2026-09-14 00:00:00.000000

`skill_name` already carries `unique=True` (uq_skill_registry_skill_name in
k1h2i3j4a5b6), which Postgres implements as a unique btree index and uses
for every equality lookup on that column (the /skills/register upsert
check, and the manifest-sync upsert's ON CONFLICT (skill_name)). The
separate ix_skill_registry_skill_name plain index added in the same
migration indexes the identical single column and is never chosen over the
unique index for planning purposes — it only adds write overhead (every
INSERT/UPDATE/DELETE on skill_registry, including the ~500-row chunked
upserts in src/skills/repository.py::bulk_upsert, maintains
it for zero read benefit). Drop it.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "o1l2m3n4a5b6"
down_revision: Union[str, None] = "n1k2l3m4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_skill_registry_skill_name", table_name="skill_registry")


def downgrade() -> None:
    op.create_index("ix_skill_registry_skill_name", "skill_registry", ["skill_name"])
