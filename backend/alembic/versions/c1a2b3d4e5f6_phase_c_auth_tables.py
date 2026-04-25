"""phase c auth tables

Revision ID: c1a2b3d4e5f6
Revises: 09ab60d66140
Create Date: 2026-04-25 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, None] = "09ab60d66140"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "oauth_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_accounts"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_oauth_accounts_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "provider", "provider_user_id", name="uq_oauth_accounts_provider_user"
        ),
    )
    op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])

    op.create_table(
        "oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("oauth_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encrypted_access_token", sa.LargeBinary(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.LargeBinary(), nullable=True),
        sa.Column(
            "token_expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_tokens"),
        sa.ForeignKeyConstraint(
            ["oauth_account_id"],
            ["oauth_accounts.id"],
            name="fk_oauth_tokens_oauth_accounts",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "oauth_account_id", name="uq_oauth_tokens_oauth_account_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("oauth_tokens")
    op.drop_index("ix_oauth_accounts_user_id", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
