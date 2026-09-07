"""apple health ingest tokens

Revision ID: l1i2j3k4a5b6
Revises: k1h2i3j4a5b6
Create Date: 2026-09-07 00:00:00.000000

Adds integration_ingest_tokens for push-style providers (Apple Health via
an iOS Shortcut) that authenticate an inbound webhook POST with a bearer
token instead of us pulling data via OAuth.

Deliberately does NOT add any table for biometric readings (recovery,
sleep, strain, HRV, workouts). Per the documented decision in
oauth_providers.py (WhoopIntegration.sync), biometric data is never
persisted in cleartext at rest — the ingest webhook caches the latest
payload transiently (Redis, short TTL) and this migration's only
responsibility is the auth credential, not the payload.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l1i2j3k4a5b6"
down_revision: Union[str, None] = "k1h2i3j4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_ingest_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "token_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA-256 hex digest of the bearer token; cleartext is never stored",
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_integration_ingest_tokens"),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name="fk_integration_ingest_tokens_integrations",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "integration_id", name="uq_ingest_token_one_per_integration"
        ),
    )
    # No separate sa.UniqueConstraint on token_hash — that would create a
    # second, unnamed unique index on the same column as the one below.
    # This named unique index is both the uniqueness guarantee and the
    # index the webhook's WHERE token_hash = :x lookup uses.
    op.create_index(
        "ix_integration_ingest_tokens_token_hash",
        "integration_ingest_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integration_ingest_tokens_token_hash",
        table_name="integration_ingest_tokens",
    )
    op.drop_table("integration_ingest_tokens")
