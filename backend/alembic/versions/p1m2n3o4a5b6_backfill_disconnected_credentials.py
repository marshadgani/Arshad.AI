"""Backfill: delete credentials for already-disconnected integrations.

Revision ID: p1m2n3o4a5b6
Revises: o1l2m3n4a5b6
Create Date: 2026-09-14 00:00:00.000002

FEAT-161: the disconnect() re-implementation now hard-deletes
integration_oauth_tokens and api_key_credentials on disconnect and
soft-revokes integration_ingest_tokens (sets revoked_at). Integrations
that were disconnected before this feature shipped still hold their
encrypted credentials in the DB — this migration removes them.

Data-only: no schema changes (DD-007 still holds — the integration row
and credential tables are unchanged). Idempotent: re-running finds an
empty "already-disconnected" set (either because there's nothing left to
scrub, or because a fresh database has no disconnected rows to begin
with) and every statement becomes a no-op.

The disconnected-integration id set is computed ONCE into a temp table
(ON COMMIT DROP — cleaned up automatically when Alembic's migration
transaction commits) instead of being re-evaluated as a correlated
subquery in each of the three DML statements below. At this app's
single-user scale the difference is immaterial, but a shared, explicitly
materialized set is the honest way to say "these three statements act on
the same snapshot of disconnected integrations" — a live-running
disconnect() flipping a row's status between two independently-evaluated
subqueries could otherwise make the ingest-token UPDATE see a different
set than the two DELETEs did.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "p1m2n3o4a5b6"
down_revision = "o1l2m3n4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Bound the wait for locks on the credential tables — a concurrent
    # disconnect() or sync() holding a row lock must not hang this
    # migration (and everything queued behind it) indefinitely.
    conn.execute(text("SET LOCAL lock_timeout = '5s'"))

    # Materialize the disconnected-integration id set exactly once so all
    # three DML statements below act on the identical snapshot.
    conn.execute(
        text(
            """
            CREATE TEMPORARY TABLE _feat161_disconnected_integration_ids
            ON COMMIT DROP
            AS
            SELECT id FROM integrations WHERE status = 'disconnected'
            """
        )
    )

    # Hard-delete OAuth tokens for every integration already disconnected.
    conn.execute(
        text(
            """
            DELETE FROM integration_oauth_tokens
            WHERE integration_id IN (
                SELECT id FROM _feat161_disconnected_integration_ids
            )
            """
        )
    )

    # Hard-delete API-key credentials for every integration already disconnected.
    conn.execute(
        text(
            """
            DELETE FROM api_key_credentials
            WHERE integration_id IN (
                SELECT id FROM _feat161_disconnected_integration_ids
            )
            """
        )
    )

    # Soft-revoke ingest tokens — do NOT delete. The row must survive so
    # services/apple_health/ingest_auth.py can distinguish "never connected"
    # (no row) from "token issued then revoked" (row with revoked_at set).
    # Only stamps rows that haven't already been soft-revoked.
    conn.execute(
        text(
            """
            UPDATE integration_ingest_tokens
            SET revoked_at = now()
            WHERE revoked_at IS NULL
              AND integration_id IN (
                  SELECT id FROM _feat161_disconnected_integration_ids
              )
            """
        )
    )


def downgrade() -> None:
    # Intentional no-op: deleted credentials are irrecoverable — the
    # encryption key for the ciphertext is not stored in this migration,
    # and even if it were, restoring raw credential bytes after a revoke
    # has potentially been sent upstream would create a false sense of
    # safety. Operators who need to roll back this data change must restore
    # from a pre-migration database snapshot (NFR-002).
    pass
