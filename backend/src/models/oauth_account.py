import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampedMixin


class OAuthAccount(Base, TimestampedMixin):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_oauth_accounts_provider_user"
        ),
        # One oauth_account per (user_id, provider) — enforced at the DB
        # level, not just by the SELECT-then-INSERT check in
        # auth/service.py's attach_oauth_account_to_user (SI-2). Every
        # lookup in this codebase (personal/_shared.py's
        # _load_usable_account — the single reader that backs both the
        # connect and status paths — and auth/service.py's own SI-2
        # query) filters on exactly these two columns and expects at
        # most one row; db.scalar() does not raise on duplicates, it
        # silently picks one. Also serves as the composite index those
        # lookups need — supersedes the old single-column index on
        # user_id (see migration m1j2k3l4a5b6).
        UniqueConstraint("user_id", "provider", name="uq_oauth_accounts_user_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str] = mapped_column(String(320), nullable=False)
