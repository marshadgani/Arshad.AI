"""Dashboard widget data derived from the user's real ingested and operational tables.

Replaces the one-time ``seed_from_mock.py`` rows the dashboard used to serve.
Every function is a pure transform over already-fetched rows so it can be
unit-tested without a database; the query layer lives in ``api/v1/dashboard.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from ..models.ai_ecosystem import AgentUsageLog
from ..models.ingested import IngestedGitHubActivity
from ..models.integration import Integration

_MAX_ITEMS = 8
_BAD_INTEGRATION_STATUSES = {"error": "critical", "expired": "warn"}


def age_label(then: datetime, now: datetime | None = None) -> str:
    """Compact relative age: '5 m', '3 h', '2 d'."""
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} m"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} d"


def _updated_label(then: datetime, now: datetime) -> str:
    # These are ages, not due dates, so never start with "Today"/"Yesterday":
    # the Tasks card styles those prefixes as overdue/due-today urgency.
    days = (now.date() - then.date()).days
    if days <= 0:
        return "Updated today"
    if days == 1:
        return "Updated yesterday"
    return f"Updated {days} d ago"


def _gh_open(
    rows: Sequence[IngestedGitHubActivity], kind: str
) -> list[IngestedGitHubActivity]:
    return [r for r in rows if r.kind == kind and (r.raw or {}).get("state") == "open"]


def _repo(row: IngestedGitHubActivity) -> str:
    return row.provider_id.rsplit("#", 1)[0]


def _gh_title(row: IngestedGitHubActivity) -> str:
    raw = row.raw or {}
    return f"{row.provider_id} {raw.get('title') or ''}".strip()


def build_tasks(
    github: Sequence[IngestedGitHubActivity], now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    tasks: list[dict[str, Any]] = []
    for row in sorted(
        _gh_open(github, "pr"), key=lambda r: r.occurred_at, reverse=True
    ):
        tasks.append(
            {
                "id": f"gh-pr-{row.id}",
                "title": f"Review {_gh_title(row)}",
                "source": "github",
                "due": _updated_label(row.occurred_at, now),
                "priority": "p1",
            }
        )
    for row in sorted(
        _gh_open(github, "issue"), key=lambda r: r.occurred_at, reverse=True
    ):
        tasks.append(
            {
                "id": f"gh-issue-{row.id}",
                "title": _gh_title(row),
                "source": "github",
                "due": _updated_label(row.occurred_at, now),
                "priority": "p2",
            }
        )
    return tasks[:_MAX_ITEMS]


def build_decisions(
    github: Sequence[IngestedGitHubActivity], now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    prs = sorted(_gh_open(github, "pr"), key=lambda r: r.occurred_at)
    return [
        {
            "id": f"gh-pr-{r.id}",
            "title": f"Review {_gh_title(r)}",
            "context": f"Open pull request in {_repo(r)}",
            "source": "github",
            "waiting_since": age_label(r.occurred_at, now),
        }
        for r in prs[:_MAX_ITEMS]
    ]


def build_focus(
    github: Sequence[IngestedGitHubActivity], now: datetime | None = None
) -> dict[str, str]:
    now = now or datetime.now(timezone.utc)
    prs = sorted(_gh_open(github, "pr"), key=lambda r: r.occurred_at)
    if prs:
        r = prs[0]
        return {
            "title": f"Review {_gh_title(r)}",
            "subtitle": f"Waiting {age_label(r.occurred_at, now)} · GitHub · P1",
            "context": f"Oldest open pull request in {_repo(r)}.",
            "action": "Open in GitHub",
        }
    issues = sorted(_gh_open(github, "issue"), key=lambda r: r.occurred_at)
    if issues:
        r = issues[0]
        return {
            "title": _gh_title(r),
            "subtitle": f"Open {age_label(r.occurred_at, now)} · GitHub · P2",
            "context": f"Oldest open issue in {_repo(r)}.",
            "action": "Open in GitHub",
        }
    return {
        "title": "Nothing urgent",
        "subtitle": "No open pull requests or issues synced",
        "context": (
            "Connect GitHub on the Integrations page and run Sync now "
            "to see your next priority here."
        ),
        "action": "Open Integrations",
    }


def build_notifications(
    integrations: Sequence[Integration], now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    items = []
    for i in integrations:
        severity = _BAD_INTEGRATION_STATUSES.get(i.status)
        if not severity:
            continue
        reference = i.last_synced_at or now
        items.append(
            {
                "id": f"int-{i.id}",
                "severity": severity,
                "title": f"{i.slug} needs attention",
                "detail": (i.last_error or f"Status: {i.status}")[:140],
                "time": age_label(reference, now),
            }
        )
    return items[:_MAX_ITEMS]


def build_agent_activity(
    logs: Sequence[AgentUsageLog], now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    return [
        {
            "id": str(log.id),
            "agent": log.agent_name,
            "message": "Run completed" if log.success else "Run failed",
            "time": age_label(log.invoked_at, now),
        }
        for log in logs[:_MAX_ITEMS]
    ]


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def build_health_habits(
    whoop: dict[str, Any] | None, apple: dict[str, Any] | None
) -> list[dict[str, str]]:
    """Up to four real readings from the connected Whoop / Apple Health payloads."""
    whoop = whoop or {}
    apple = apple or {}
    recovery = whoop.get("recovery") or {}
    sleep = whoop.get("sleep") or {}
    strain = whoop.get("strain") or {}

    cells: list[dict[str, str]] = []

    score = _num(recovery.get("recovery_score"))
    if score is not None:
        cells.append({"name": "Recovery", "value": f"{score:.0f}%", "delta": "Whoop"})

    in_bed = _num(sleep.get("total_in_bed_time_milli"))
    awake = _num(sleep.get("total_awake_time_milli")) or 0.0
    perf = _num(sleep.get("sleep_performance_percentage"))
    if in_bed is not None and in_bed > awake:
        hours = (in_bed - awake) / 3_600_000
        delta = f"Whoop · {perf:.0f}% performance" if perf is not None else "Whoop"
        cells.append({"name": "Sleep", "value": f"{hours:.1f} h", "delta": delta})
    elif (apple_sleep := _num(apple.get("sleep_hours"))) is not None:
        cells.append(
            {"name": "Sleep", "value": f"{apple_sleep:.1f} h", "delta": "Apple Health"}
        )

    day_strain = _num(strain.get("score"))
    if day_strain is not None:
        cells.append({"name": "Strain", "value": f"{day_strain:.1f}", "delta": "Whoop"})

    steps = _num(apple.get("steps"))
    if steps is not None:
        cells.append(
            {"name": "Steps", "value": f"{int(steps):,}", "delta": "Apple Health"}
        )

    hrv = _num(recovery.get("hrv_rmssd_milli")) or _num(
        apple.get("heart_rate_variability_ms")
    )
    if hrv is not None:
        source = "Whoop" if _num(recovery.get("hrv_rmssd_milli")) else "Apple Health"
        cells.append({"name": "HRV", "value": f"{hrv:.0f} ms", "delta": source})

    resting = _num(recovery.get("resting_heart_rate")) or _num(
        apple.get("resting_heart_rate")
    )
    if resting is not None:
        source = "Whoop" if _num(recovery.get("resting_heart_rate")) else "Apple Health"
        cells.append(
            {"name": "Resting HR", "value": f"{resting:.0f} bpm", "delta": source}
        )

    return cells[:4]
