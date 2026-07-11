"""Dashboard widget models — Phase A.

Mirrors every shape currently in ``frontend/src/data/mockData.ts``.
String PKs (e.g. ``t1``, ``e1``) preserve the stable IDs the frontend
already keys on, so seeded data remains URL-quotable and testable.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Enum,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampedMixin

# ── Enums ──────────────────────────────────────────────────────────
SOURCE_VALUES = ("github", "gmail", "notion", "linear", "slack", "calendar")
SEVERITY_VALUES = ("critical", "warn", "info", "ok")
AGENT_HEALTH_VALUES = ("healthy", "training", "degraded", "offline")
CALENDAR_TAG_VALUES = ("work", "personal", "family", "health")
PRIORITY_VALUES = ("p0", "p1", "p2", "p3")
EVENT_SOURCE_VALUES = ("Google", "Apple", "Outlook")


SourceEnum = Enum(*SOURCE_VALUES, name="source_enum")
SeverityEnum = Enum(*SEVERITY_VALUES, name="severity_enum")
AgentHealthEnum = Enum(*AGENT_HEALTH_VALUES, name="agent_health_enum")
CalendarTagEnum = Enum(*CALENDAR_TAG_VALUES, name="calendar_tag_enum")
PriorityEnum = Enum(*PRIORITY_VALUES, name="priority_enum")
EventSourceEnum = Enum(*EVENT_SOURCE_VALUES, name="event_source_enum")


# ── Tasks ──────────────────────────────────────────────────────────
class Task(TimestampedMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(SourceEnum)
    due: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(PriorityEnum)


# ── Events ─────────────────────────────────────────────────────────
class Event(TimestampedMixin, Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    start: Mapped[str] = mapped_column(String(32))
    duration: Mapped[str] = mapped_column(String(32))
    calendar: Mapped[str] = mapped_column(CalendarTagEnum)
    source: Mapped[str] = mapped_column(EventSourceEnum)


# ── Cross-domain agent roster ──────────────────────────────────────
class AgentGlobal(TimestampedMixin, Base):
    """Top-level agent roster shown on the Dashboard's Agent Activity widget.

    Distinct from per-domain ``DomainAgent`` rows in ``models.domain``.
    """

    __tablename__ = "agents_global"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    domain: Mapped[str] = mapped_column(String(64))
    health: Mapped[str] = mapped_column(AgentHealthEnum)
    uptime: Mapped[str] = mapped_column(String(16))
    accuracy: Mapped[int] = mapped_column(Integer)
    last_action: Mapped[str] = mapped_column(String(256))
    last_run: Mapped[str] = mapped_column(String(64))


# ── Decisions ──────────────────────────────────────────────────────
class Decision(TimestampedMixin, Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    context: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(SourceEnum)
    waiting_since: Mapped[str] = mapped_column(String(32))


# ── Agent activity ticker ──────────────────────────────────────────
class AgentTick(TimestampedMixin, Base):
    __tablename__ = "agent_activity"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(String(512))
    time: Mapped[str] = mapped_column(String(32))


# ── Notifications ──────────────────────────────────────────────────
class Notification(TimestampedMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    severity: Mapped[str] = mapped_column(SeverityEnum)
    title: Mapped[str] = mapped_column(String(256))
    detail: Mapped[str] = mapped_column(String(512))
    time: Mapped[str] = mapped_column(String(32))


# ── News ───────────────────────────────────────────────────────────
class NewsItem(TimestampedMixin, Base):
    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(128))


# ── Knowledge suggestions ──────────────────────────────────────────
class KnowledgeSuggestion(TimestampedMixin, Base):
    """Auto-generated suggestions for the knowledge-search widget.

    The frontend consumes only the text; UUIDs exist so re-seeds are
    idempotent and the rows are addressable from later admin tooling.
    """

    __tablename__ = "knowledge_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    text: Mapped[str] = mapped_column(String(512))


# ── Quick actions ──────────────────────────────────────────────────
class QuickAction(TimestampedMixin, Base):
    __tablename__ = "quick_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    hint: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ── Health & habits ────────────────────────────────────────────────
class HealthHabit(TimestampedMixin, Base):
    """One row per habit. Frontend keys by name (``sleep``/``steps``/…)."""

    __tablename__ = "health_habits"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(64))
    delta: Mapped[str] = mapped_column(String(128))


# ── Singletons (id == 1 enforced) ──────────────────────────────────
class DailyBriefing(TimestampedMixin, Base):
    __tablename__ = "daily_briefing"
    __table_args__ = (CheckConstraint("id = 1", name="ck_daily_briefing_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    greeting: Mapped[str] = mapped_column(String(128))
    date_label: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(2048))


class FocusBlock(TimestampedMixin, Base):
    __tablename__ = "focus_now"
    __table_args__ = (CheckConstraint("id = 1", name="ck_focus_now_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    title: Mapped[str] = mapped_column(String(256))
    subtitle: Mapped[str] = mapped_column(String(256))
    context: Mapped[str] = mapped_column(String(1024))
    action: Mapped[str] = mapped_column(String(64))


class Weather(TimestampedMixin, Base):
    __tablename__ = "weather"
    __table_args__ = (CheckConstraint("id = 1", name="ck_weather_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    temp: Mapped[str] = mapped_column(String(16))
    condition: Mapped[str] = mapped_column(String(64))
    city: Mapped[str] = mapped_column(String(64))


class Commute(TimestampedMixin, Base):
    __tablename__ = "commute"
    __table_args__ = (CheckConstraint("id = 1", name="ck_commute_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    eta: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(32))
    dest: Mapped[str] = mapped_column(String(128))
