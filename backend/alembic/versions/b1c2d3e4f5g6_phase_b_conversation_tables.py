"""phase b conversation tables

Revision ID: b1c2d3e4f5g6
Revises: f1b2c3d4e5f6
Create Date: 2026-04-26 06:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c2d3e4f5g6"
down_revision: Union[str, None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default="New chat"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_conversation_sessions_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_conversation_sessions_user_updated",
        "conversation_sessions",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("usage_input_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.id"],
            name="fk_conversation_messages_sessions",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_conversation_messages_session_created",
        "conversation_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_messages_session_created",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index(
        "ix_conversation_sessions_user_updated",
        table_name="conversation_sessions",
    )
    op.drop_table("conversation_sessions")
