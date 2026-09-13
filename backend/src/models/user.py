import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampedMixin


class User(Base, TimestampedMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # unique=True is sufficient — Postgres backs a UNIQUE constraint with its
    # own index automatically. index=True was dropped (migration
    # m1j2k3l4a5b6) because it created a second, functionally identical
    # unique index (ix_users_email) alongside the constraint's own
    # (uq_users_email), doubling the index-maintenance cost on every user
    # write for no query-planning benefit.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
