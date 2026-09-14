"""dag_trigger_queue: dedup index + inflight unique constraint (FEAT-144)

Two DB-level gaps in the sync-enqueue path:

1. The dedup SELECT in personal/_shared.py.make_sync_via_dag (filters on
   user_id + dag_id + status IN ('pending','picked'), ordered by
   requested_at) has no covering index — only
   ix_dag_trigger_queue_user_id_requested_at (no dag_id) and
   ix_dag_trigger_queue_status_requested_at (no user_id) exist, so
   Postgres has to scan every row for the user (or every pending/picked
   row across all users) and filter the rest in memory. The same
   fallback shape (user_id + dag_id, no status filter) is used by
   routers.sync_job_status when no job_id is supplied. This migration
   adds ix_dag_trigger_queue_user_id_dag_id_requested_at to cover both.

2. That dedup SELECT and the subsequent INSERT are two separate
   statements, not one atomic operation. Two concurrent sync requests
   (an impatient double-click, or a client retry racing the first
   request) can both pass the "nothing in flight" check before either
   commits, producing two DagTriggerQueue rows for the same
   (user_id, dag_id) and triggering the provider API twice — exactly
   the double-trigger the dedup check exists to prevent. This mirrors
   the oauth_accounts race closed by m1j2k3l4a5b6: a partial UNIQUE
   index on (user_id, dag_id) WHERE status IN ('pending','picked')
   turns the losing concurrent INSERT into a clean IntegrityError
   (handled in _shared.py._sync) instead of a silent duplicate. Scoped
   to pending/picked only, so completed/failed history rows for the
   same user+dag are never constrained.

Safe to run against existing data: at most one pending/picked row per
(user_id, dag_id) has ever been possible to reach on purpose (the
application-level dedup check), so a pre-existing violation here would
itself be evidence of this exact race having already occurred — the
migration fails loudly in that case rather than silently picking a
survivor.

Revision ID: n1k2l3m4a5b6
Revises: m1j2k3l4a5b6
Create Date: 2026-09-14 00:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n1k2l3m4a5b6"
down_revision: Union[str, None] = "m1j2k3l4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_dag_trigger_queue_user_id_dag_id_requested_at",
        "dag_trigger_queue",
        ["user_id", "dag_id", "requested_at"],
    )
    op.create_index(
        "uq_dag_trigger_queue_user_dag_inflight",
        "dag_trigger_queue",
        ["user_id", "dag_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'picked')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_dag_trigger_queue_user_dag_inflight", table_name="dag_trigger_queue"
    )
    op.drop_index(
        "ix_dag_trigger_queue_user_id_dag_id_requested_at",
        table_name="dag_trigger_queue",
    )
