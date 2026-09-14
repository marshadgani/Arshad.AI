"""skill_registry.category CHECK constraint

Revision ID: p1m2n3o4a5b6
Revises: o1l2m3n4a5b6
Create Date: 2026-09-14 00:00:00.000000

Prior to this migration `category` was `String(50)` with no constraint
beyond a code comment listing the four legal values. The only place that
value was actually validated was `RegisterSkillRequest` (a Pydantic
`Literal`) on the `/skills/register` endpoint — but
`src/skills/service.py::sync_from_manifest` bulk-upserts rows
parsed straight out of `backend/src/skills/manifest.json` via
`INSERT ... ON CONFLICT`, bypassing that endpoint and its validation
entirely. A malformed or hand-edited manifest could silently write an
out-of-range category that the frontend's four-way filter/pill UI
(`SKILL_FILTERS` in AiEcosystem.tsx) doesn't know how to bucket.

Adds `ck_skill_registry_category` so the constraint holds for every write
path, not just the ones that happen to go through Pydantic. See
`src/skills/categories.py` for the canonical value list this must stay in
sync with — this migration hardcodes them (Alembic migrations must be
self-contained and immutable per database.md) rather than importing that
module.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "p1m2n3o4a5b6"
down_revision: Union[str, None] = "o1l2m3n4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CATEGORIES = ("development", "security", "data", "other")


def upgrade() -> None:
    op.create_check_constraint(
        "ck_skill_registry_category",
        "skill_registry",
        "category IN (" + ", ".join(f"'{c}'" for c in _CATEGORIES) + ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skill_registry_category", "skill_registry", type_="check")
