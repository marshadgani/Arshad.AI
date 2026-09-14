"""SQLAlchemy model for the Skill Registry."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.skills.categories import SKILL_CATEGORIES

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
    # Value is one of SKILL_CATEGORIES (src/skills/categories.py); the Python
    # type stays `str` (SQLAlchemy's Mapped[] has no first-class Literal
    # support without a custom TypeDecorator), but the CHECK constraint below
    # makes the four-value invariant a database-level guarantee rather than
    # something only the API layer's Pydantic validation happens to enforce
    # — it also covers rows written by src/skills/repository.py's manifest
    # bulk-upsert, which builds INSERT ... ON CONFLICT statements directly
    # from parsed JSON and never passes through RegisterSkillRequest.
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")

    # No explicit index on skill_name: unique=True above already gives it a
    # unique btree index. A second plain index on the same single column
    # (ix_skill_registry_skill_name, dropped in o1l2m3n4a5b6) would be pure
    # write-amplification — every insert/update/delete maintains it for zero
    # read benefit, since the unique index already serves equality lookups.
    __table_args__ = (
        Index("ix_skill_registry_category_display_name", "category", "display_name"),
        CheckConstraint(
            "category IN (" + ", ".join(f"'{c}'" for c in SKILL_CATEGORIES) + ")",
            name="ck_skill_registry_category",
        ),
    )
