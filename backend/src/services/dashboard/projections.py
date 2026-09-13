"""Row -> widget-dict translation, and the public ``derive_*`` entry points.

This is the only module in the package that knows both "what an ingested
row looks like" and "what a dashboard widget field is called". It composes
``formatting`` (how a value is displayed), ``rows`` (how a value is safely
read) and ``heuristics`` (whether a row qualifies at all); each projection
below is therefore a flat field mapping with its guards stated up front.

Zero I/O: no AsyncSession, no await, no network calls, no env read at
import time. Every function is total over malformed input — a bad row is
skipped or defaulted, never allowed to raise and take the whole widget down
with it. Fault isolation lives in ``rows.project_all``, not here.

The route layer (``api/v1/dashboard.py``) decides *which* rows to ask for
and what to do when derivation yields nothing; it does not know how a JSONB
payload becomes a widget field.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from .formatting import (
    TITLE_LIMIT,
    clean_title,
    humanize_due,
    humanize_elapsed,
    humanize_time,
)
from .heuristics import (
    apply_priority_heuristic,
    apply_severity_heuristic,
    is_actionable_pr,
)
from .rows import (
    derived_of,
    occurred_at_of,
    pr_opened_at,
    project_all,
    raw_of,
    repo_or_github,
)
from .widget_types import (
    AgentTickDict,
    DecisionDict,
    GitHubActivityDict,
    GitHubActivityState,
    NotificationDict,
    TaskDict,
)

if TYPE_CHECKING:
    from src.models.ingested import IngestedGitHubActivity, IngestedGmailThread

logger = logging.getLogger(__name__)


def _numbered_title(raw: dict[str, Any], *, limit: int = TITLE_LIMIT) -> str:
    """'#42 Fix the thing' — how both GitHub widgets label a PR or issue.

    The ``#N`` prefix is dropped when the payload carries no usable number
    rather than rendering a bare '#'.
    """
    number = raw.get("number")
    title = raw.get("title") or ""
    return clean_title(f"#{number} {title}" if number else title, limit=limit)


# ── Hybrid widgets (live rows with a seed fallback) ────────────────


def project_task(row: IngestedGmailThread) -> TaskDict | None:
    occurred_at = occurred_at_of(row)
    if occurred_at is None:
        return None
    derived = derived_of(row)
    labels = derived.get("labels")
    return {
        "id": str(row.id),
        "title": clean_title(derived.get("subject") or raw_of(row).get("snippet")),
        "source": "gmail",
        "due": humanize_due(occurred_at),
        "priority": apply_priority_heuristic(
            labels if isinstance(labels, list) else []
        ),
    }


def project_activity(row: IngestedGitHubActivity) -> AgentTickDict | None:
    occurred_at = occurred_at_of(row)
    if occurred_at is None:
        return None
    return {
        "id": str(row.id),
        "agent": repo_or_github(row),
        "message": _numbered_title(raw_of(row), limit=80),
        "time": humanize_time(occurred_at),
    }


def project_notification(row: IngestedGitHubActivity) -> NotificationDict | None:
    severity = apply_severity_heuristic(row)
    occurred_at = occurred_at_of(row)
    if severity is None or occurred_at is None:
        return None
    severity_word = "Critical" if severity == "critical" else "Warning"
    return {
        "id": str(row.id),
        "severity": severity,
        "title": f"{severity_word} issue: {repo_or_github(row)}",
        "detail": clean_title(raw_of(row).get("title")),
        "time": humanize_time(occurred_at),
    }


def project_pr_decision(
    row: IngestedGitHubActivity, *, github_user_id: str | None
) -> DecisionDict | None:
    """One ``ingested_github_activity`` PR row -> ``DecisionDict``, or
    ``None`` if the row is not an actionable decision for this user.

    Guards, in order: the PR has a usable "opened at" timestamp; it is
    ``state == 'open'``; it is not a draft; and ``is_actionable_pr``
    resolves a context string. No try/except here — ``project_all`` owns
    fault isolation for the whole widget.
    """
    raw = raw_of(row)
    opened_at = pr_opened_at(row)
    if opened_at is None:
        return None
    if raw.get("state") != "open":
        return None
    if bool(raw.get("draft")):
        return None
    context = is_actionable_pr(raw, github_user_id=github_user_id)
    if context is None:
        return None

    return {
        "id": str(row.id),
        "title": _numbered_title(raw),
        "context": context,
        "source": "github",
        "waiting_since": humanize_elapsed(opened_at),
    }


def derive_tasks_from_gmail(rows: Sequence[IngestedGmailThread]) -> list[TaskDict]:
    """Flagged Gmail threads -> TaskResponse-shaped dicts."""
    return project_all(rows, project_task, widget="tasks")


def derive_activities_from_github(
    rows: Sequence[IngestedGitHubActivity],
) -> list[AgentTickDict]:
    """PR rows (kind='pr') -> AgentTickResponse-shaped dicts."""
    return project_all(rows, project_activity, widget="agent-activity")


def derive_notifications_from_github(
    rows: Sequence[IngestedGitHubActivity],
) -> list[NotificationDict]:
    """Issue rows (kind='issue') -> NotificationResponse-shaped dicts.

    Rows without a critical/warn label are silently skipped — this is not
    a general-purpose issue feed, only an alert feed.
    """
    return project_all(rows, project_notification, widget="notifications")


def derive_decisions_from_github(
    rows: Sequence[IngestedGitHubActivity], *, github_user_id: str | None
) -> list[DecisionDict]:
    """Open, non-draft PR rows (kind='pr') blocked on ``github_user_id`` ->
    DecisionResponse-shaped dicts. See ``heuristics.is_actionable_pr`` for
    the reviewer/author rule."""
    return project_all(
        rows,
        partial(project_pr_decision, github_user_id=github_user_id),
        widget="decisions",
    )


# ── GitHub activity feed (FEAT-139) ────────────────────────────────
#
# Deliberately does NOT reuse rows.repo_or_github above: that helper yields
# the bare repo name ("repo") for the agent-ticker's narrow column, whereas
# this feed shows the fully-qualified "owner/repo". Two different
# presentation contracts, not accidental duplication — unifying them would
# change one widget's output.


def _resolve_state(raw: dict[str, Any]) -> GitHubActivityState:
    """'open' | 'closed' — untrusted JSONB defaults to 'open' rather than
    propagating whatever string a third-party payload happens to contain."""
    raw_state = raw.get("state")
    if raw_state in ("open", "closed"):
        return cast(GitHubActivityState, raw_state)
    return "open"


def _resolve_number(raw: dict[str, Any], num_part: str) -> int | None:
    """PR/issue number from ``raw.number``, falling back to the ``#N`` suffix
    of ``provider_id``. Neither source is trusted to be a valid integer."""
    raw_number = raw.get("number")
    if isinstance(raw_number, int):
        return raw_number
    try:
        return int(num_part)
    except ValueError:
        # Covers both an empty suffix (no "#" in provider_id) and a
        # non-numeric one.
        return None


def project_github_activity(row: IngestedGitHubActivity) -> GitHubActivityDict | None:
    """Projects one ``ingested_github_activity`` row into the plain dict
    consumed by ``GitHubActivityResponse``.

    ``raw`` is a verbatim third-party JSONB payload and may be missing any
    key or contain an explicit ``null`` — every lookup below is defensive.
    Rows with an unrecognised ``kind`` are dropped (return ``None``) rather
    than raising, so one malformed row never breaks the whole widget. Note
    that ``row.kind`` being statically typed ``GitHubActivityKind`` (see
    ``models/ingested.py``) is a claim about what the ingestion pipeline
    writes, not a DB-enforced constraint — the column is still a plain
    VARCHAR, so this runtime guard stays even though a type checker
    considers it unreachable.
    """
    kind = row.kind
    if kind not in ("issue", "pr"):
        logger.warning("github-activity: unrecognised kind=%r id=%s", kind, row.id)
        return None

    raw = row.raw or {}

    repository, _, num_part = row.provider_id.rpartition("#")
    if not repository:
        repository = row.provider_id

    # Reject any scheme other than https:// — raw is attacker-influenceable
    # JSONB, and this is the only guard between it and a target="_blank"
    # anchor href on the frontend (javascript:/data: URL injection).
    url = raw.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        url = None

    is_pr_merged = kind == "pr" and bool(raw.get("merged_at"))

    return {
        "id": str(row.id),
        "title": raw.get("title") or "(untitled)",
        "url": url,
        "number": _resolve_number(raw, num_part),
        "repository": repository,
        "kind": kind,
        "state": "merged" if is_pr_merged else _resolve_state(raw),
        "is_draft": kind == "pr" and bool(raw.get("draft")),
        "author": (raw.get("user") or {}).get("login") or None,
        "updated_at": row.occurred_at.isoformat(),
    }


def derive_github_activity(
    rows: Sequence[IngestedGitHubActivity],
) -> list[GitHubActivityDict]:
    """Project every row, dropping the ones ``project_github_activity``
    rejects or that raise on malformed ``raw`` JSONB. Callers get the
    skipped count from ``len(rows) - len(result)``.
    """
    return project_all(rows, project_github_activity, widget="github-activity")
