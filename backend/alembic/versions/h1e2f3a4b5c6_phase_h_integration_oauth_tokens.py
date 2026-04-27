"""phase h integration oauth tokens

Revision ID: h1e2f3a4b5c6
Revises: g1d2e3f4a5b6
Create Date: 2026-04-26 21:30:00.000000

Adds integration_oauth_tokens for the generic OAuth callback flow shipped
in Phase H. Storing tokens here (rather than reusing oauth_tokens, which
is keyed to the login OAuthAccount) keeps the integration's token lifecycle
independent of the user's primary login.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h1e2f3a4b5c6"
down_revision: Union[str, None] = "g1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "encrypted_access_token",
            postgresql.BYTEA(),
            nullable=False,
            comment="AES-GCM ciphertext of the access token",
        ),
        sa.Column(
            "encrypted_refresh_token",
            postgresql.BYTEA(),
            nullable=True,
            comment="AES-GCM ciphertext of the refresh token (null when provider doesn't issue one)",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
            comment="Provider-specific data (e.g., user profile snapshot, athlete_id for Strava)",
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
            name="fk_int_oauth_integration",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_integration_oauth_tokens"),
        sa.UniqueConstraint("integration_id", name="uq_int_oauth_one_per_integration"),
    )


def downgrade() -> None:
    op.drop_table("integration_oauth_tokens")
