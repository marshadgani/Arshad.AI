"""null out plaintext-credential-bearing integration error strings

Revision ID: o1l2m3n4a5b6
Revises: n1k2l3m4a5b6
Create Date: 2026-09-14 00:00:00.000001

FEAT-069: prior to this release, several integration providers
(OpenWeatherMap, Stack Overflow, and every project_apikey provider built
on integrations/project/_factory.py or integrations/project/_shared.py)
persisted the raw str() of upstream exceptions into integrations.last_error
and dag_trigger_queue.error_text. httpx.HTTPStatusError.__str__() embeds
the full request URL, and several of these providers authenticate via a
query-string parameter (OpenWeatherMap's `?appid=...`, Stack Overflow's
`?access_token=...`), so a failed request could leave a plaintext API key
sitting in Postgres — readable by anyone with SELECT on these tables, and
previously re-served verbatim by GET /api/v1/integrations, GET
/api/v1/obsidian (error field), and GET /api/v1/agents/... (error_text).

The forward-only code fix (safe_detail()/error_summary() in
backend/src/utils/errors.py, applied at every write site) stops new leaks.
This migration remediates data already written before the fix landed.

Unconditional on both tables — dag_trigger_queue.error_text is only ever
written on failure (services/queue_worker.py), so any status predicate
would exclude exactly the leaked rows.

downgrade() is an intentional no-op: these were ephemeral diagnostic
strings that may have contained plaintext API keys, and restoring them
would re-introduce the vulnerability this migration remediates.
"""

from __future__ import annotations

from alembic import op

revision = "o1l2m3n4a5b6"
down_revision = "n1k2l3m4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE integrations SET last_error = NULL WHERE last_error IS NOT NULL")
    op.execute(
        "UPDATE dag_trigger_queue SET error_text = NULL WHERE error_text IS NOT NULL"
    )


def downgrade() -> None:
    # Intentional no-op — see module docstring. Do not restore data here.
    pass
