"""phase f ingestion tables

Revision ID: f1b2c3d4e5f6
Revises: c1a2b3d4e5f6
Create Date: 2026-04-26 03:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dag_trigger_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dag_id", sa.Text(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column(
            "requested_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("picked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_dag_trigger_queue"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_dag_trigger_queue_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_dag_trigger_queue_status_requested_at",
        "dag_trigger_queue",
        ["status", "requested_at"],
    )
    op.create_index(
        "ix_dag_trigger_queue_user_id_requested_at",
        "dag_trigger_queue",
        ["user_id", "requested_at"],
    )

    for table_name, extra_unique_cols, extra_columns in [
        ("ingested_calendar_events", ["user_id", "provider_id"], []),
        ("ingested_gmail_threads", ["user_id", "provider_id"], []),
        (
            "ingested_github_activity",
            ["user_id", "kind", "provider_id"],
            [sa.Column("kind", sa.String(length=20), nullable=False)],
        ),
    ]:
        cols = [
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "occurred_at", postgresql.TIMESTAMP(timezone=True), nullable=False
            ),
            sa.Column("provider_id", sa.String(length=255), nullable=False),
            *extra_columns,
            sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "ingested_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ]
        op.create_table(
            table_name,
            *cols,
            sa.PrimaryKeyConstraint("id", name=f"pk_{table_name}"),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name=f"fk_{table_name}_users",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(*extra_unique_cols, name=f"uq_{table_name}_unique"),
        )
        op.create_index(
            f"ix_{table_name}_user_occurred",
            table_name,
            ["user_id", "occurred_at"],
        )

    op.create_table(
        "ingested_analytics_summary",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("metric_value", sa.Numeric(), nullable=False),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "ingested_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingested_analytics_summary"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ingested_analytics_summary_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "metric_key",
            "occurred_at",
            name="uq_ingested_analytics_user_metric_window",
        ),
    )
    op.create_index(
        "ix_ingested_analytics_user_metric",
        "ingested_analytics_summary",
        ["user_id", "metric_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingested_analytics_user_metric", table_name="ingested_analytics_summary"
    )
    op.drop_table("ingested_analytics_summary")
    for t in (
        "ingested_github_activity",
        "ingested_gmail_threads",
        "ingested_calendar_events",
    ):
        op.drop_index(f"ix_{t}_user_occurred", table_name=t)
        op.drop_table(t)
    op.drop_index(
        "ix_dag_trigger_queue_user_id_requested_at", table_name="dag_trigger_queue"
    )
    op.drop_index(
        "ix_dag_trigger_queue_status_requested_at", table_name="dag_trigger_queue"
    )
    op.drop_table("dag_trigger_queue")
