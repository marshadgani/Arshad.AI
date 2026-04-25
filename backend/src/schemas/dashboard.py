"""Pydantic v2 response schemas for dashboard endpoints.

Field names match the TypeScript shapes in
``frontend/src/data/mockData.ts`` exactly so the frontend's existing
type imports continue to work after the rewire.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Tasks ──────────────────────────────────────────────────────────
class TaskResponse(_ORM):
    id: str
    title: str
    source: Literal["github", "gmail", "notion", "linear", "slack", "calendar"]
    due: str
    priority: Literal["p0", "p1", "p2", "p3"]


# ── Events ─────────────────────────────────────────────────────────
class EventResponse(_ORM):
    id: str
    title: str
    start: str
    duration: str
    calendar: Literal["work", "personal", "family", "health"]
    source: Literal["Google", "Apple", "Outlook"]


# ── Cross-domain agent roster ──────────────────────────────────────
class AgentResponse(_ORM):
    id: str
    name: str
    domain: str
    health: Literal["healthy", "training", "degraded", "offline"]
    uptime: str
    accuracy: int
    last_action: str = Field(serialization_alias="lastAction")
    last_run: str = Field(serialization_alias="lastRun")


# ── Decisions ──────────────────────────────────────────────────────
class DecisionResponse(_ORM):
    id: str
    title: str
    context: str
    source: Literal["github", "gmail", "notion", "linear", "slack", "calendar"]
    waiting_since: str = Field(serialization_alias="waitingSince")


# ── Agent activity ticker ──────────────────────────────────────────
class AgentTickResponse(_ORM):
    id: str
    agent: str
    message: str
    time: str


# ── Notifications ──────────────────────────────────────────────────
class NotificationResponse(_ORM):
    id: str
    severity: Literal["critical", "warn", "info", "ok"]
    title: str
    detail: str
    time: str


# ── News ───────────────────────────────────────────────────────────
class NewsResponse(_ORM):
    id: str
    title: str
    source: str


# ── Quick actions ──────────────────────────────────────────────────
class QuickActionResponse(_ORM):
    id: str
    label: str
    hint: str | None = None


# ── Health & habits ────────────────────────────────────────────────
class HealthHabitResponse(_ORM):
    name: str
    value: str
    delta: str


# ── Singletons ─────────────────────────────────────────────────────
class DailyBriefingResponse(_ORM):
    greeting: str
    date_label: str = Field(serialization_alias="date")
    summary: str


class FocusBlockResponse(_ORM):
    title: str
    subtitle: str
    context: str
    action: str


class WeatherResponse(_ORM):
    temp: str
    condition: str
    city: str


class CommuteResponse(_ORM):
    eta: str
    mode: str
    dest: str
