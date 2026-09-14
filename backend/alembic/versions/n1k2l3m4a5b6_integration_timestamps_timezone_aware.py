"""make integration timestamp columns timezone-aware

Revision ID: n1k2l3m4a5b6
Revises: m1j2k3l4a5b6
Create Date: 2026-09-14 00:00:00.000000

Fixes FEAT-157: every integration sync() writes a tz-aware
datetime.now(timezone.utc) into these three columns, which were declared
as plain (tz-naive) TIMESTAMP. asyncpg raises "can't subtract
offset-naive and offset-aware datetimes" when binding the aware value,
so POST /api/v1/integrations/{slug}/sync 500s for every provider, and
storing a Phase-H OAuth token's expiry or an Apple Health ingest token's
last-used time fails the same way.

USING <col> AT TIME ZONE 'UTC' preserves existing naive values (already
UTC in practice — every writer used datetime.now(timezone.utc) or
func.now()) by reinterpreting them as UTC instead of shifting the clock.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n1k2l3m4a5b6"
down_revision: Union[str, None] = "m1j2k3l4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "integrations",
        "last_synced_at",
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="last_synced_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "integration_oauth_tokens",
        "expires_at",
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="expires_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "integration_ingest_tokens",
        "last_used_at",
        type_=sa.TIMESTAMP(timezone=True),
        postgresql_using="last_used_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "integration_ingest_tokens",
        "last_used_at",
        type_=sa.TIMESTAMP(timezone=False),
        postgresql_using="last_used_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "integration_oauth_tokens",
        "expires_at",
        type_=sa.TIMESTAMP(timezone=False),
        postgresql_using="expires_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "integrations",
        "last_synced_at",
        type_=sa.TIMESTAMP(timezone=False),
        postgresql_using="last_synced_at AT TIME ZONE 'UTC'",
    )
