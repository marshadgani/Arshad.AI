"""SQLAlchemy model for the Skill Registry."""

from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampedMixin


class SkillRegistry(TimestampedMixin, Base):
    __tablename__ = "skill_registry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # unique=True is sufficient here — Postgres backs a UNIQUE constraint with
    # its own btree index automatically, so a separate explicit index on the
    # same column would be a redundant duplicate (extra storage + write cost
    # with zero query benefit). See migration p1m2n3o4a5b6 which drops the
    # duplicate that k1h2i3j4a5b6 originally created.
    skill_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_repo: Mapped[str] = mapped_column(
        String(100), nullable=False, default="unknown"
    )
    # 'development' | 'security' | 'data' | 'other'
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
