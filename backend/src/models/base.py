from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Aware UTC now, for TIMESTAMP(timezone=True) column defaults.

    datetime.utcnow() returns a naive datetime; passing it as a Python-side
    default/onupdate for a tz-aware column makes asyncpg raise "can't
    subtract offset-naive and offset-aware datetimes" the moment that
    default fires (see migration n1k2l3m4a5b6's docstring for the
    production incident this caused via DagTriggerQueue.requested_at).
    """
    return datetime.now(timezone.utc)


class TimestampedMixin:
    """created_at / updated_at columns with PG-side defaults.

    Declares naive TIMESTAMP WITHOUT TIME ZONE, which is what most legacy
    tables have. Tables created as timestamptz use TimestampedTZMixin.
    """

    created_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), onupdate=func.now()
    )


class TimestampedTZMixin:
    """Same columns as TimestampedMixin, declared timezone-aware.

    Use this for tables whose created_at / updated_at are TIMESTAMP WITH TIME
    ZONE in Postgres. Declaring them naive makes `alembic revision
    --autogenerate` (compare_type=True) propose a harmful ALTER back to
    TIMESTAMP WITHOUT TIME ZONE that drops the offset.
    """

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )
