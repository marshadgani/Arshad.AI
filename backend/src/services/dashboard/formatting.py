"""Display formatting for dashboard widget fields.

Pure string/datetime functions. This module knows nothing about ORM rows,
JSONB payloads, widgets, or the database — it is the leaf of the dashboard
package's dependency graph, which is what makes it exhaustively testable
without a single fixture.

Two of these formats are load-bearing contracts with the frontend rather
than free-form prose; see ``humanize_due`` and ``humanize_elapsed``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TITLE_LIMIT = 120


def _tz() -> Any:
    """Resolve DASHBOARD_TZ lazily so a bad env value can never break import.

    Reads the env var on every call (no caching) — DASHBOARD_TZ can change
    between requests/tests (e.g. ``monkeypatch.setenv``), and a cached
    result would silently keep serving the first-seen timezone forever.
    """
    name = os.getenv("DASHBOARD_TZ", "Europe/London")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def assume_utc(dt: datetime) -> datetime:
    """Attach UTC to a naive datetime.

    Ingested ``raw`` timestamps are untrusted third-party strings and often
    parse naive. Treating them as UTC keeps them comparable with an aware
    ``now`` instead of raising TypeError and silently dropping the row.
    """
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def as_local(dt: datetime) -> datetime:
    """Normalise any datetime (naive assumed UTC) to DASHBOARD_TZ."""
    return assume_utc(dt).astimezone(_tz())


def humanize_due(dt: datetime, *, now: datetime | None = None) -> str:
    """'Yesterday HH:MM' | 'Today HH:MM' | 'Dow DD Mon' — matches the exact
    prefix contract TasksCard.dueClass() parses. Never emit ISO8601 here.
    """
    now = now or datetime.now(timezone.utc)
    local_dt = as_local(dt)
    local_now = as_local(now)
    delta_days = (local_now.date() - local_dt.date()).days

    if delta_days == 1:
        return f"Yesterday {local_dt.strftime('%H:%M')}"
    if delta_days == 0:
        return f"Today {local_dt.strftime('%H:%M')}"
    return local_dt.strftime("%a %d %b")


def humanize_time(dt: datetime) -> str:
    """'HH:MM' in DASHBOARD_TZ — matches AgentTick/Notification 'time' field."""
    return as_local(dt).strftime("%H:%M")


def humanize_elapsed(dt: datetime, *, now: datetime | None = None) -> str:
    """Human-readable elapsed duration for display: 'just now' | 'N m' |
    'N h' | 'N d'.

    Purely cosmetic — DecisionQueueCard renders this as opaque text and
    parses nothing (unlike ``humanize_due``, which TasksCard.dueClass()
    does parse). The format is chosen to match the existing seed rows so
    live and seed modes look identical. A negative or future ``dt`` (clock
    skew between the ingestion write and this request) clamps to
    'just now' rather than rendering a nonsensical negative duration.
    """
    delta_seconds = (
        assume_utc(now or datetime.now(timezone.utc)) - assume_utc(dt)
    ).total_seconds()
    if delta_seconds < 60:
        return "just now"
    minutes = int(delta_seconds // 60)
    if minutes < 60:
        return f"{minutes} m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h"
    days = hours // 24
    return f"{days} d"


def extract_repo_from_provider_id(provider_id: str) -> str:
    """'owner/repo#123' -> 'repo'; '#123' -> ''; 'nohash' -> 'nohash'."""
    if not provider_id:
        return ""
    prefix = provider_id.split("#", 1)[0]
    return prefix.rsplit("/", 1)[-1]


def clean_title(text: str | None, limit: int = TITLE_LIMIT) -> str:
    """Collapse whitespace and ellipsise, with a placeholder for empty text."""
    if not text:
        return "(no subject)"
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 3)] + "..."
