"""skill registry table

Revision ID: k1h2i3j4a5b6
Revises: j1g2h3i4a5b6
Create Date: 2026-07-12 10:00:00.000000

Adds skill_registry table for tracking Claude skills installed from external repos.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "k1h2i3j4a5b6"
down_revision: Union[str, None] = "j1g2h3i4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_name", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "source_repo", sa.String(100), nullable=False, server_default="unknown"
        ),
        sa.Column("category", sa.String(50), nullable=False, server_default="other"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_registry"),
        sa.UniqueConstraint("skill_name", name="uq_skill_registry_skill_name"),
    )
    op.create_index("ix_skill_registry_skill_name", "skill_registry", ["skill_name"])


def downgrade() -> None:
    op.drop_index("ix_skill_registry_skill_name", table_name="skill_registry")
    op.drop_table("skill_registry")
