"""make remaining naive integration_ingest_tokens columns timezone-aware

Revision ID: n1k2l3m4a5b6
Revises: m1j2k3l4a5b6
Create Date: 2026-09-14 00:00:00.000000

Fixes FEAT-157: POST /api/v1/integrations/{slug}/sync 500ed with
asyncpg.exceptions.DataError: "can't subtract offset-naive and
offset-aware datetimes".

Initial diagnosis (wrong, corrected during Merge-to-Main gate review —
the code-reviewer agent traced the actual DDL history and a direct
`information_schema.columns` check against production confirmed it)
assumed `integrations.last_synced_at` and `integration_oauth_tokens
.expires_at` were tz-naive. They were not — both were already created as
`TIMESTAMP WITH TIME ZONE` (see g1d2e3f4a5b6, h1e2f3a4b5c6). Only the
Python-side SQLAlchemy model had drifted to a naive declaration; this
revision's model-file counterpart corrects that drift without any DDL
change for those two columns (a same-type "aware -> aware" ALTER would
have been a needless no-op at best and, per the code-reviewer's
correction, actively risked reinterpreting values through the session's
`TimeZone` setting at worst — `col AT TIME ZONE 'UTC'` on an
already-`timestamptz` column round-trips through a naive intermediate).

The actual, verified root cause: `DagTriggerQueue.requested_at`
(`backend/src/models/dag_trigger.py`) is `TIMESTAMP(timezone=True)` but
its Python-side `default=datetime.utcnow` returns a *naive* datetime.
Every integration `sync()` that goes through `make_sync_via_dag()`
inserts a `DagTriggerQueue` row without setting `requested_at`
explicitly, so the ORM default fires and asyncpg rejects the naive value
for the aware column — this is the actual write that was 500ing, not
`Integration.last_synced_at`. Fixed at the code level (no migration
needed — the column was already the right type): `dag_trigger.py` and
three other models with the same `default=datetime.utcnow` pattern
(`obsidian.py`, `conversation.py`, `ingested.py`) now use
`models.base.utcnow` (aware) instead.

What *is* genuinely naive in Postgres, confirmed via
`information_schema.columns` against production: `integration_ingest_
tokens.last_used_at` and `.revoked_at`. Neither has a client-side
tz-aware writer today (`last_used_at` is written via
`datetime.now(timezone.utc)` in `apple_health.py`'s ingest endpoint,
which would hit the identical asyncpg error the first time that code
path runs; `revoked_at` is currently only ever `func.now()` or `None`,
but is fixed here too rather than leaving a fourth near-identical
migration for later).

USING <col> AT TIME ZONE 'UTC' reinterprets the existing naive value as
UTC (every writer already used UTC) rather than shifting it through the
session's TimeZone setting.
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
    # integration_ingest_tokens is tiny at this app's single-user scale,
    # so the ACCESS EXCLUSIVE lock + rewrite this takes is itself cheap —
    # but with no timeout, a stuck connection holding even an ACCESS
    # SHARE lock on it would hang the migration (and every query queued
    # behind it) indefinitely instead of failing loud.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.alter_column(
        "integration_ingest_tokens",
        "last_used_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="last_used_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "integration_ingest_tokens",
        "revoked_at",
        existing_type=sa.TIMESTAMP(timezone=False),
        type_=sa.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="revoked_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "integration_ingest_tokens",
        "revoked_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="revoked_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "integration_ingest_tokens",
        "last_used_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        type_=sa.TIMESTAMP(timezone=False),
        existing_nullable=True,
        postgresql_using="last_used_at AT TIME ZONE 'UTC'",
    )
