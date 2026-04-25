"""Domain catalogue models — Phase A.

Mirrors the ``domains`` Record + ``navItems`` array from
``frontend/src/data/mockData.ts``. Per CLAUDE.md §19, six domains
exist (calendar/email/github/ai-core/data-pipeline/infrastructure)
plus the seven user-facing ones the dashboard exposes
(finance/shopify/stocks/health/learning/home/travel). The schema
treats them uniformly — the frontend's ``DomainConfig`` shape works
for both groups.
"""

import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .dashboard import AgentHealthEnum  # reuse the enum across model files
from .database import Base, TimestampedMixin


APPLICATION_STATUS_VALUES = ("live", "beta", "planned")
ApplicationStatusEnum = Enum(*APPLICATION_STATUS_VALUES, name="application_status_enum")


# ── Domain header ──────────────────────────────────────────────────
class Domain(TimestampedMixin, Base):
    __tablename__ = "domains"

    slug: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    emoji: Mapped[str] = mapped_column(String(8))
    tagline: Mapped[str] = mapped_column(String(256))

    kpis: Mapped[list["DomainKPI"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan", order_by="DomainKPI.ord"
    )
    applications: Mapped[list["DomainApplication"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )
    agents: Mapped[list["DomainAgent"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )
    feed: Mapped[list["DomainFeedRow"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )


# ── Domain KPIs ────────────────────────────────────────────────────
class DomainKPI(TimestampedMixin, Base):
    __tablename__ = "domain_kpis"
    __table_args__ = (Index("ix_domain_kpis_domain_slug", "domain_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("domains.slug", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(64))
    delta: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ord: Mapped[int] = mapped_column(Integer)

    domain: Mapped["Domain"] = relationship(back_populates="kpis")


# ── Domain applications ────────────────────────────────────────────
class DomainApplication(TimestampedMixin, Base):
    __tablename__ = "domain_applications"
    __table_args__ = (Index("ix_domain_applications_domain_slug", "domain_slug"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("domains.slug", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(ApplicationStatusEnum)

    domain: Mapped["Domain"] = relationship(back_populates="applications")


# ── Domain agents ──────────────────────────────────────────────────
class DomainAgent(TimestampedMixin, Base):
    """Per-domain agent display row.

    Distinct from ``AgentGlobal`` (the cross-domain roster shown on
    the Dashboard's Agent Activity widget). Per-domain agents power
    the Agents panel of each ``DomainPage``.
    """
    __tablename__ = "domain_agents"
    __table_args__ = (Index("ix_domain_agents_domain_slug", "domain_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("domains.slug", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512))
    health: Mapped[str] = mapped_column(AgentHealthEnum)
    uptime: Mapped[str] = mapped_column(String(16))
    accuracy: Mapped[int] = mapped_column(Integer)
    last_action: Mapped[str] = mapped_column(String(256))
    last_run: Mapped[str] = mapped_column(String(64))

    domain: Mapped["Domain"] = relationship(back_populates="agents")


# ── Domain feed rows ───────────────────────────────────────────────
class DomainFeedRow(TimestampedMixin, Base):
    __tablename__ = "domain_feed_rows"
    __table_args__ = (Index("ix_domain_feed_rows_domain_slug", "domain_slug"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("domains.slug", ondelete="CASCADE")
    )
    message: Mapped[str] = mapped_column(String(512))
    time: Mapped[str] = mapped_column(String(32))

    domain: Mapped["Domain"] = relationship(back_populates="feed")


# ── Sidebar nav ────────────────────────────────────────────────────
class NavItem(TimestampedMixin, Base):
    __tablename__ = "nav_items"

    path: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str] = mapped_column(String(8))
    domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ord: Mapped[int] = mapped_column(Integer)
