"""oauth_accounts: unique (user_id, provider)

FEAT-143 — the new "attach a provider to the current user" flow
(auth/service.py attach_oauth_account_to_user, SI-2) enforces "one
oauth_account per (user_id, provider)" only in application code: it
SELECTs for an existing row, then INSERTs if none is found. Two
concurrent attach requests for the same user+provider (double-click on
"Connect", or a retried POST after a slow redirect) can both pass that
SELECT before either COMMITs, producing two oauth_accounts rows for the
same (user_id, provider). Every reader in this codebase
(_shared.py._scope_gap, _shared.py.status_from_oauth_account,
auth/service.py's own SI-2 lookup) uses `db.scalar(select(...).where(
user_id=..., provider=...))`, which does not raise on multiple matching
rows — it silently returns whichever row Postgres happens to return
first, non-deterministically. A duplicate row is a silent data
integrity bug, not just a missing index.

This migration adds a real UNIQUE constraint on (user_id, provider),
turning that race into a clean IntegrityError — already handled by the
retry-once wrapper in both upsert_user_from_oauth and
attach_oauth_account_to_user (see auth/service.py's `except
IntegrityError: await db.rollback(); return await
_attach_once(...)` pattern) — and gives every (user_id, provider)
lookup above a composite index instead of the single-column
ix_oauth_accounts_user_id plus a provider filter applied after the
index scan.

The old single-column index is redundant once the composite index
exists (user_id is the leading column), so it is dropped rather than
kept alongside it.

Safe to run against existing data: FEAT-143's attach flow model
(google/github) never predates this migration, and Phase C's original
login flow already only ever created a single oauth_accounts row per
(user_id, provider) — a duplicate here would indicate the very race
this migration closes, so upgrade() fails loudly instead of silently
choosing which duplicate to keep.

Revision ID: m1j2k3l4a5b6
Revises: l1i2j3k4a5b6
Create Date: 2026-09-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "m1j2k3l4a5b6"
down_revision: Union[str, None] = "l1i2j3k4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_oauth_accounts_user_id", table_name="oauth_accounts")
    op.create_unique_constraint(
        "uq_oauth_accounts_user_provider",
        "oauth_accounts",
        ["user_id", "provider"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_oauth_accounts_user_provider", "oauth_accounts", type_="unique"
    )
    op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])
