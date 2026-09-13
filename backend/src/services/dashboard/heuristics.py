"""Business policy for the dashboard widgets.

Every function here answers a product question — "is this email urgent?",
"is this issue worth alerting on?", "is this PR blocked on me?" — as a pure
predicate over an ingested row or its ``raw`` payload. None of them format
anything or build a widget dict; that is ``projections``' job.

The split matters because these are the parts most likely to change on
product feedback (a new label, a different precedence rule). Isolating them
means such a change touches one small file with no rendering code in it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .rows import raw_of
from .widget_types import GitHubIssueSeverity, GmailPriority

if TYPE_CHECKING:
    from src.models.ingested import IngestedGitHubActivity

# Labels that make a GitHub issue worth surfacing as a critical notification.
_CRITICAL_LABELS = {"blocker", "critical", "security", "p0", "sev1"}
_WARN_LABELS = {"bug", "regression"}


def apply_priority_heuristic(labels: list[str]) -> GmailPriority:
    """Gmail label set -> task priority. Total over all four values."""
    upper = {label.upper() for label in labels}
    starred = "STARRED" in upper
    important = "IMPORTANT" in upper
    if starred and important:
        return "p0"
    if starred:
        return "p1"
    if important:
        return "p2"
    return "p3"


def apply_severity_heuristic(row: IngestedGitHubActivity) -> GitHubIssueSeverity | None:
    """'critical' | 'warn' | None — for a GitHub issue row (kind='issue')."""
    names: set[str] = set()
    for label in raw_of(row).get("labels") or []:
        # GitHub sends label objects; a hand-written or legacy payload may
        # carry plain strings. Anything else is ignored.
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str):
            names.add(name.lower())
    if names & _CRITICAL_LABELS:
        return "critical"
    if names & _WARN_LABELS:
        return "warn"
    return None


def is_actionable_pr(raw: dict[str, Any], *, github_user_id: str | None) -> str | None:
    """Returns a context sentence when a PR is blocked on ``github_user_id``,
    else ``None``.

    Two mutually exclusive predicates over ``requested_reviewers`` (see
    system design amendment A1):

    * REVIEWER — ``github_user_id`` appears in ``requested_reviewers`` ->
      'Waiting on your review'.
    * AUTHOR — ``requested_reviewers`` is an empty list AND the PR's author
      is ``github_user_id`` -> 'Open PR awaiting your merge decision'. An
      open, non-draft PR the user authored with zero outstanding review
      requests is genuinely blocked on them and nobody else.

    These are structurally disjoint (reviewer requires a non-empty list,
    author requires an empty one), so no row can ever satisfy both — there
    is deliberately no precedence rule to encode.

    A non-list ``requested_reviewers`` (malformed JSONB) is treated as "not
    empty and does not contain you" rather than as "nobody is blocking" —
    it must not be silently reinterpreted as the empty-list author case.

    Do NOT reach for ``raw['mergeable_state']`` or ``raw['mergeable']`` to
    strengthen this check: those fields exist only on the single-PR "full"
    GitHub API object, not on the LIST payload this project ingests and
    stores in ``raw`` (see ``tools/github/list_prs.py``). Reading them here
    would silently drop every row.
    """
    if github_user_id is None:
        return None

    reviewers = raw.get("requested_reviewers")
    if isinstance(reviewers, list):
        reviewer_ids = {str(r.get("id")) for r in reviewers if isinstance(r, dict)}
        if github_user_id in reviewer_ids:
            return "Waiting on your review"
        if not reviewers:
            author_id = str((raw.get("user") or {}).get("id", ""))
            if author_id == github_user_id:
                return "Open PR awaiting your merge decision"
    return None
