"""drop redundant users email index

Revision ID: m1j2k3l4a5b6
Revises: l1i2j3k4a5b6
Create Date: 2026-09-13 00:00:00.000000

FEAT-142 DB audit finding: c1a2b3d4e5f6 (phase c auth tables) created TWO
unique indexes on users.email —

  1. `uq_users_email`, the unique index Postgres creates automatically to
     back `UniqueConstraint("email", name="uq_users_email")`
  2. `ix_users_email`, an explicit `op.create_index(..., unique=True)` on
     the same single column

Both are hit on every INSERT/UPDATE of `users` (including every OAuth
login — `_upsert_once` in backend/src/auth/service.py writes/refreshes a
`users` row on each callback) for zero query-planning benefit: Postgres
never needs two identical unique btree indexes to satisfy either
uniqueness or `WHERE email = ...` lookups (auth/service.py, auth/routers.py
`/me` all query by primary key or this single column). Drops the
redundant explicit index; `uq_users_email` (and the FK-safe uniqueness
guarantee it provides) is untouched.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "m1j2k3l4a5b6"
down_revision: Union[str, None] = "l1i2j3k4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")


def downgrade() -> None:
    op.create_index("ix_users_email", "users", ["email"], unique=True)
