"""phase g integrations tables

Revision ID: g1d2e3f4a5b6
Revises: b1c2d3e4f5g6
Create Date: 2026-04-26 19:30:00.000000

Adds two tables:
  - integrations: parent record per (user, slug) for personal_oauth or
    per (slug) for project_apikey. Tracks status, last_synced_at, last_error,
    and a config jsonb for per-provider settings.
  - api_key_credentials: AES-GCM-encrypted API keys for project_apikey
    integrations (Render, Vercel, Supabase, etc.). Personal OAuth integrations
    continue to use the existing oauth_accounts + oauth_tokens.

The integration_id FK on oauth_accounts is intentionally NOT added — backfill
is handled by the personal-OAuth provider's connect() looking up by
(user_id, provider) and adopting the existing row.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g1d2e3f4a5b6"
down_revision: Union[str, None] = "b1c2d3e4f5g6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="null for project_apikey integrations",
        ),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column(
            "kind",
            sa.String(32),
            nullable=False,
            comment="personal_oauth or project_apikey",
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="disconnected",
            comment="connected | disconnected | error | expired",
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_integrations_user"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_integrations"),
        sa.UniqueConstraint("user_id", "slug", name="uq_integrations_user_slug"),
    )
    op.create_index(
        "ix_integrations_user_id", "integrations", ["user_id"], unique=False
    )
    op.create_index("ix_integrations_slug", "integrations", ["slug"], unique=False)

    op.create_table(
        "api_key_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "encrypted_key",
            postgresql.BYTEA(),
            nullable=False,
            comment="AES-GCM ciphertext: [12-byte nonce][ciphertext + 16-byte tag]",
        ),
        sa.Column(
            "key_prefix",
            sa.String(16),
            nullable=False,
            comment="First 6 chars of the raw key for UI display ('rnd_xxx', 'vrcl_xxx')",
        ),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            ondelete="CASCADE",
            name="fk_apikey_integration",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_key_credentials"),
        sa.UniqueConstraint("integration_id", name="uq_apikey_one_per_integration"),
    )


def downgrade() -> None:
    op.drop_table("api_key_credentials")
    op.drop_index("ix_integrations_slug", table_name="integrations")
    op.drop_index("ix_integrations_user_id", table_name="integrations")
    op.drop_table("integrations")
