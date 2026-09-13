"""dashboard widget index optimizations

FEAT-136 database audit: the live dashboard queries in
backend/src/api/v1/dashboard.py filter on predicates the existing
ix_ingested_*_user_occurred indexes do not cover, forcing Postgres to
apply those predicates as a post-index-scan filter instead of an index
condition:

  * /api/v1/dashboard/agent-activity and /notifications filter on
    (user_id, kind) in addition to ordering by occurred_at — the
    existing index only covers (user_id, occurred_at), so `kind` is a
    residual filter scanned row-by-row.
  * /api/v1/dashboard/tasks filters on
    jsonb_typeof(raw->'_derived'->'labels') = 'array' AND
    jsonb_array_length(raw->'_derived'->'labels') > 0 — a JSONB
    expression the plain (user_id, occurred_at) index cannot serve at
    all.

This migration adds a composite index for the kind-filtered GitHub
queries and a partial expression index matching the /tasks predicate
exactly, so both become fully index-served instead of filter-scanned.

Revision ID: m1j2k3l4a5b6
Revises: l1i2j3k4a5b6
Create Date: 2026-09-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m1j2k3l4a5b6"
down_revision: Union[str, None] = "l1i2j3k4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_ingested_github_user_kind_occurred",
        "ingested_github_activity",
        ["user_id", "kind", "occurred_at"],
    )
    op.execute(
        """
        CREATE INDEX ix_ingested_gmail_flagged_user_occurred
        ON ingested_gmail_threads (user_id, occurred_at)
        WHERE jsonb_typeof(raw->'_derived'->'labels') = 'array'
          AND jsonb_array_length(raw->'_derived'->'labels') > 0
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ingested_gmail_flagged_user_occurred")
    op.drop_index(
        "ix_ingested_github_user_kind_occurred",
        table_name="ingested_github_activity",
    )
