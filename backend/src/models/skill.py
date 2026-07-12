"""SQLAlchemy model for the Skill Registry."""

from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampedMixin


class SkillRegistry(TimestampedMixin, Base):
    __tablename__ = "skill_registry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    skill_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_repo: Mapped[str] = mapped_column(
        String(100), nullable=False, default="unknown"
    )
    # 'development' | 'security' | 'data' | 'other'
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")

    __table_args__ = (Index("ix_skill_registry_skill_name", "skill_name"),)
