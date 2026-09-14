"""add user password_hash

Revision ID: m1j2k3l4a5b6
Revises: l1i2j3k4a5b6
Create Date: 2026-09-14 00:00:00.000000

Additive-only: adds a nullable password_hash column to users, enabling
email/password login as a second credential type alongside Google/GitHub
OAuth (FEAT-143). NULL means "OAuth-only account" and is a permanent,
first-class state — most rows will stay NULL forever. No index: the
column is never used in a WHERE predicate.

password_hash is written only by backend/scripts/set_password.py — there
is no HTTP registration endpoint (single-user app; OAuth remains the
sole account-creation path, see ADR-6 in FEAT-143's system design).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m1j2k3l4a5b6"
down_revision: Union[str, None] = "l1i2j3k4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
