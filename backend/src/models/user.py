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
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # NULL = OAuth-only account (most accounts, permanently — this is a
    # first-class state, not a migration artefact). Presence drives the
    # dummy_verify vs verify_password branch decision in the password
    # login handler. Written only by backend/scripts/set_password.py.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
