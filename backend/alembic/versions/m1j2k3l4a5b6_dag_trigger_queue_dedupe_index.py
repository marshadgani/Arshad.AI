"""dag trigger queue dedupe index

Revision ID: m1j2k3l4a5b6
Revises: l1i2j3k4a5b6
Create Date: 2026-09-14 00:00:00.000000

FEAT-144 follow-up. make_sync_via_dag() (backend/src/integrations/personal/
_shared.py) checks for an existing pending/recently-picked job before
enqueuing a new one via `SELECT ... FOR UPDATE`. That only locks rows that
already exist — it does nothing to prevent two concurrent "Sync now"
requests that both observe zero pending rows from both proceeding to
INSERT, which would silently double-queue the same (user, dag) sync.

This adds:
  1. A composite index on (user_id, dag_id, requested_at) — the dedupe
     check and GET /{slug}/sync/status poll both filter on user_id AND
     dag_id, which neither pre-existing index on this table covers.
  2. A partial UNIQUE index on (user_id, dag_id) WHERE status = 'pending'
     — the hard database-level guarantee the app-level check can't
     provide by itself. The app now catches the resulting IntegrityError
     and folds it into the existing dedupe response instead of raising.

Only 'pending' is covered (not 'picked') because the picked-lease window
is time-based (picked_at > now() - lease), which a static partial index
predicate cannot express; the 'picked' case is deliberately left as an
application-level-only safeguard, same as before this migration.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "m1j2k3l4a5b6"
down_revision: Union[str, None] = "l1i2j3k4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CREATE UNIQUE INDEX fails outright if duplicates already exist, and
    # they almost certainly do: before this fix "Sync now" enqueued a new
    # pending row on every click and (with no worker on Render) nothing
    # ever drained them. Collapse each (user_id, dag_id) group down to its
    # newest pending row first — the older ones are redundant enqueues for
    # work that has not happened, so dropping them loses nothing.
    op.execute(
        """
        DELETE FROM dag_trigger_queue q
        USING dag_trigger_queue newer
        WHERE q.status = 'pending'
          AND newer.status = 'pending'
          AND newer.user_id = q.user_id
          AND newer.dag_id = q.dag_id
          AND (newer.requested_at, newer.id) > (q.requested_at, q.id)
        """
    )
    op.create_index(
        "ix_dag_trigger_queue_user_id_dag_id_requested_at",
        "dag_trigger_queue",
        ["user_id", "dag_id", "requested_at"],
    )
    op.create_index(
        "uq_dag_trigger_queue_pending_user_dag",
        "dag_trigger_queue",
        ["user_id", "dag_id"],
        unique=True,
        postgresql_where=text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_dag_trigger_queue_pending_user_dag", table_name="dag_trigger_queue"
    )
    op.drop_index(
        "ix_dag_trigger_queue_user_id_dag_id_requested_at",
        table_name="dag_trigger_queue",
    )
