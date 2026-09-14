"""domain_feed_rows: composite index for bounded per-domain feed query (FEAT-148)

DB-specialist audit of the domain catalogue queries (backend/src/api/v1/
domains.py) found two issues, both fixed here plus a matching ORM change:

1. Domain.feed / Domain.applications / Domain.agents relationships had no
   `order_by`. Without an ORDER BY, Postgres result order is undefined —
   the "Recent activity" panel (labelled "last 24 h" in the UI) could
   render in a different order on every request. Fixed in
   backend/src/models/domain.py by adding deterministic order_by clauses
   (feed: created_at desc; applications/agents: name).

2. GET /api/v1/domains/{slug} eager-loaded the *entire* domain_feed_rows
   history for a domain via selectinload with no LIMIT, violating the
   "never fetch unbounded rows" rule in .claude/rules/database.md — the
   table only ever grows. backend/src/api/v1/domains.py now fetches feed
   rows with a separate bounded (LIMIT 20), ordered (created_at desc)
   query instead of an unbounded selectinload.

This migration adds the composite index that bounded query needs. The
existing single-column ix_domain_feed_rows_domain_slug only helps the
equality filter; it can't also satisfy the ORDER BY, so Postgres would
still sort every matching row before applying the LIMIT. A composite
index on (domain_slug, created_at DESC) — equality column first, sort
column second, matching the query's WHERE + ORDER BY shape — lets
Postgres walk the index in the row's final order and stop after 20
rows. The old single-column index becomes redundant (its leftmost
column is a prefix of the new one) and is dropped.

Revision ID: o1l2m3n4a5b6
Revises: n1k2l3m4a5b6
Create Date: 2026-09-14 00:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o1l2m3n4a5b6"
down_revision: Union[str, None] = "n1k2l3m4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_domain_feed_rows_domain_slug", table_name="domain_feed_rows")
    op.create_index(
        "ix_domain_feed_rows_domain_slug_created_at",
        "domain_feed_rows",
        ["domain_slug", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_domain_feed_rows_domain_slug_created_at", table_name="domain_feed_rows"
    )
    op.create_index(
        "ix_domain_feed_rows_domain_slug", "domain_feed_rows", ["domain_slug"]
    )
