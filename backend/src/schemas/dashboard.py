"""Pydantic v2 response schemas for dashboard endpoints.

Field names match the TypeScript shapes in
``frontend/src/data/mockData.ts`` exactly so the frontend's existing
type imports continue to work after the rewire.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import ORMBase as _ORM


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


class WeatherResponse(BaseModel):
    """Not an ``_ORM`` subclass — the OpenWeatherMap-connected states carry
    no backing row, so this schema is always constructed field-by-field by
    ``services/weather/service.py`` rather than via
    ``model_validate(orm_obj)``.

    Four legal ``connected``/``needs_reauth``/``degraded`` combinations,
    mirroring ``WhoopDashboard`` (``schemas/whoop.py``):

    1. disconnected — ``connected=False``, both flags ``False``, and
       ``temp``/``condition``/``city`` must all be ``None``.
    2. connected + needs_reauth — payload fields must be ``None``.
    3. connected + degraded — payload fields must be ``None``.
    4. connected + healthy — both flags ``False``, payload may be populated.

    ``frozen=True`` because the state-machine validator below runs only on
    construction: on a mutable model a field could be reassigned after
    validation into an illegal combination nothing re-checks.
    """

    model_config = ConfigDict(frozen=True)

    temp: str | None = None
    condition: str | None = None
    city: str | None = None
    connected: bool = False
    needs_reauth: bool = False
    degraded: bool = False

    @model_validator(mode="after")
    def _check_state_combination(self) -> "WeatherResponse":
        if not self.connected and (self.needs_reauth or self.degraded):
            raise ValueError("needs_reauth/degraded require connected=True.")
        if self.needs_reauth and self.degraded:
            raise ValueError("needs_reauth and degraded are mutually exclusive.")
        healthy = self.connected and not (self.needs_reauth or self.degraded)
        if not healthy and (self.temp, self.condition, self.city) != (None, None, None):
            raise ValueError(
                "temp/condition/city are populated only in the connected, "
                "healthy state."
            )
        return self


class CommuteResponse(_ORM):
    eta: str
    mode: str
    dest: str


# ── GitHub activity feed ───────────────────────────────────────────
class GitHubActivityResponse(BaseModel):
    """Not an ``_ORM`` subclass — validated from the plain dict produced by
    ``project_github_activity`` (JSONB extraction), never from the ORM row
    directly, so ``from_attributes`` support is unneeded here."""

    id: str
    title: str
    url: str | None
    number: int | None
    repository: str
    kind: Literal["issue", "pr"]
    state: Literal["open", "closed", "merged"]
    is_draft: bool = Field(serialization_alias="isDraft")
    author: str | None
    updated_at: str = Field(serialization_alias="updatedAt")
