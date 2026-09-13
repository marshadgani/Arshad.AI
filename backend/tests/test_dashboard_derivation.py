"""Tests for the pure-function layers of ``src/services/dashboard/``
— ``formatting``, ``heuristics``, ``rows`` and ``projections``.

No I/O, no DB fixtures. Uses a lightweight SimpleNamespace stand-in for ORM
rows since derivation only ever reads .id/.raw/.occurred_at/.provider_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.schemas.dashboard import (
    AgentTickResponse,
    DecisionResponse,
    NotificationResponse,
    TaskResponse,
)
from src.services.dashboard import formatting, heuristics, projections, rows


def _gmail_row(*, labels=None, subject=None, snippet="hi", occurred_at=None):
    raw = {"snippet": snippet}
    if labels is not None or subject is not None:
        derived = {}
        if labels is not None:
            derived["labels"] = labels
        if subject is not None:
            derived["subject"] = subject
        raw["_derived"] = derived
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw=raw,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )


def _github_row(
    *,
    kind="issue",
    number=42,
    title="Something broke",
    labels=None,
    provider_id="owner/repo#42",
    occurred_at=None,
):
    raw = {"number": number, "title": title, "labels": labels or []}
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw=raw,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        provider_id=provider_id,
        kind=kind,
    )


def _pr_row(
    *,
    state="open",
    draft=False,
    number=7,
    title="Fix the widget",
    requested_reviewers=None,
    author_id="1",
    created_at=None,
    occurred_at=None,
):
    raw = {
        "number": number,
        "title": title,
        "state": state,
        "draft": draft,
        "user": {"id": author_id},
    }
    if requested_reviewers is not None:
        raw["requested_reviewers"] = requested_reviewers
    if created_at is not None:
        raw["created_at"] = created_at
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw=raw,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        provider_id="owner/repo#7",
        kind="pr",
    )


# ── humanize_due ───────────────────────────────────────────────────


def test_humanize_due_yesterday():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(days=1)
    assert formatting.humanize_due(dt, now=now).startswith("Yesterday")


def test_humanize_due_today():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now.replace(hour=8)
    assert formatting.humanize_due(dt, now=now).startswith("Today")


def test_humanize_due_older_is_weekday():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(days=3)
    result = formatting.humanize_due(dt, now=now)
    assert not result.startswith("Yesterday")
    assert not result.startswith("Today")


# ── apply_priority_heuristic ─────────────────────────────────────


def test_priority_important_only():
    assert heuristics.apply_priority_heuristic(["IMPORTANT"]) == "p2"


def test_priority_starred_only():
    assert heuristics.apply_priority_heuristic(["STARRED"]) == "p1"


def test_priority_both():
    assert heuristics.apply_priority_heuristic(["STARRED", "IMPORTANT"]) == "p0"


def test_priority_neither():
    assert heuristics.apply_priority_heuristic([]) == "p3"


# ── apply_severity_heuristic ─────────────────────────────────────


def test_severity_warn_label():
    row = _github_row(labels=[{"name": "bug"}])
    assert heuristics.apply_severity_heuristic(row) == "warn"


def test_severity_critical_label():
    row = _github_row(labels=[{"name": "security"}])
    assert heuristics.apply_severity_heuristic(row) == "critical"


def test_severity_blocker_label():
    row = _github_row(labels=[{"name": "blocker"}])
    assert heuristics.apply_severity_heuristic(row) == "critical"


def test_severity_no_matching_label():
    row = _github_row(labels=[{"name": "question"}])
    assert heuristics.apply_severity_heuristic(row) is None


# ── extract_repo_from_provider_id ─────────────────────────────────


def test_extract_repo_standard():
    assert formatting.extract_repo_from_provider_id("owner/repo#123") == "repo"


def test_extract_repo_no_owner():
    assert formatting.extract_repo_from_provider_id("#123") == ""


def test_extract_repo_no_hash():
    assert formatting.extract_repo_from_provider_id("nohash") == "nohash"


def test_extract_repo_empty():
    assert formatting.extract_repo_from_provider_id("") == ""


# ── derive_tasks_from_gmail ────────────────────────────────────────


def test_derive_tasks_from_gmail_uses_subject_over_snippet():
    row = _gmail_row(
        labels=["STARRED"], subject="Real subject", snippet="fallback snippet"
    )
    tasks = projections.derive_tasks_from_gmail([row])
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Real subject"
    TaskResponse.model_validate(tasks[0])


def test_derive_tasks_from_gmail_falls_back_to_snippet():
    row = _gmail_row(labels=["IMPORTANT"], snippet="just a snippet")
    tasks = projections.derive_tasks_from_gmail([row])
    assert tasks[0]["title"] == "just a snippet"


def test_derive_tasks_from_gmail_missing_derived_no_exception():
    row = _gmail_row()
    tasks = projections.derive_tasks_from_gmail([row])
    assert len(tasks) == 1
    assert tasks[0]["priority"] == "p3"


def test_derive_tasks_from_gmail_malformed_raw_defaults_without_exception():
    row = SimpleNamespace(
        id=uuid.uuid4(), raw="not-a-dict", occurred_at=datetime.now(timezone.utc)
    )
    tasks = projections.derive_tasks_from_gmail([row])
    assert len(tasks) == 1
    assert tasks[0]["title"] == "(no subject)"
    assert tasks[0]["priority"] == "p3"


def test_derive_tasks_title_truncation():
    long_title = "x" * 200
    row = _gmail_row(labels=["STARRED"], subject=long_title)
    tasks = projections.derive_tasks_from_gmail([row])
    assert len(tasks[0]["title"]) <= 120
    assert tasks[0]["title"].endswith("...")


def test_derive_tasks_schema_validates():
    row = _gmail_row(labels=["STARRED", "IMPORTANT"], subject="Sign this")
    tasks = projections.derive_tasks_from_gmail([row])
    validated = TaskResponse.model_validate(tasks[0])
    assert validated.source == "gmail"


# ── derive_activities_from_github ─────────────────────────────────


def test_derive_activities_from_github_shape():
    row = _github_row(
        kind="pr", number=7, title="Fix the bug", provider_id="acme/widgets#7"
    )
    activities = projections.derive_activities_from_github([row])
    assert activities[0]["agent"] == "widgets"
    assert activities[0]["message"] == "#7 Fix the bug"
    AgentTickResponse.model_validate(activities[0])


def test_derive_activities_malformed_row_skipped():
    row = SimpleNamespace(id=uuid.uuid4(), raw=None, occurred_at=None, provider_id="x")
    assert projections.derive_activities_from_github([row]) == []


# ── derive_notifications_from_github ──────────────────────────────


def test_derive_notifications_only_critical_or_warn():
    critical = _github_row(labels=[{"name": "security"}], provider_id="acme/widgets#1")
    benign = _github_row(labels=[{"name": "question"}], provider_id="acme/widgets#2")
    notifications = projections.derive_notifications_from_github([critical, benign])
    assert len(notifications) == 1
    assert notifications[0]["severity"] == "critical"
    NotificationResponse.model_validate(notifications[0])


def test_derive_notifications_warn_severity():
    row = _github_row(labels=[{"name": "bug"}], provider_id="acme/widgets#3")
    notifications = projections.derive_notifications_from_github([row])
    assert notifications[0]["severity"] == "warn"


def test_derive_notifications_empty_labels_skipped():
    row = _github_row(labels=[], provider_id="acme/widgets#4")
    assert projections.derive_notifications_from_github([row]) == []


# ── humanize_elapsed ───────────────────────────────────────────────
# REQ: BR-136-001 (waiting_since field), FR-136-003 (waiting_since derivation)


def test_humanize_elapsed_under_one_minute():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(seconds=30)
    assert formatting.humanize_elapsed(dt, now=now) == "just now"


def test_humanize_elapsed_exactly_zero_seconds():
    """At the boundary (delta == 0) — clamps to 'just now', not '0 m'."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    assert formatting.humanize_elapsed(now, now=now) == "just now"


def test_humanize_elapsed_exactly_one_minute():
    """60 s crosses the minute boundary: must return '1 m', not 'just now'."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(seconds=60)
    assert formatting.humanize_elapsed(dt, now=now) == "1 m"


def test_humanize_elapsed_59_minutes():
    """Last value before the hour boundary must be '59 m', not '0 h'."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(minutes=59)
    assert formatting.humanize_elapsed(dt, now=now) == "59 m"


def test_humanize_elapsed_exactly_60_minutes():
    """60 m crosses the hour boundary: must return '1 h', not '60 m'."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(minutes=60)
    assert formatting.humanize_elapsed(dt, now=now) == "1 h"


def test_humanize_elapsed_minutes():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(minutes=5)
    assert formatting.humanize_elapsed(dt, now=now) == "5 m"


def test_humanize_elapsed_23_hours():
    """Last value before the day boundary must be '23 h', not '0 d'."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(hours=23)
    assert formatting.humanize_elapsed(dt, now=now) == "23 h"


def test_humanize_elapsed_hours():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(hours=3)
    assert formatting.humanize_elapsed(dt, now=now) == "3 h"


def test_humanize_elapsed_exactly_24_hours():
    """24 h crosses the day boundary: must return '1 d', not '24 h'."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(hours=24)
    assert formatting.humanize_elapsed(dt, now=now) == "1 d"


def test_humanize_elapsed_days():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(days=2)
    assert formatting.humanize_elapsed(dt, now=now) == "2 d"


def test_humanize_elapsed_multi_day():
    """Multi-day span: 9 d (mirrors the A2-pin test in the PR route)."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now - timedelta(days=9)
    assert formatting.humanize_elapsed(dt, now=now) == "9 d"


def test_humanize_elapsed_future_clock_skew_clamps_to_just_now():
    """Future dt (clock skew between ingestion write and this request) must
    clamp to 'just now', never produce a negative duration string.
    REQ: NFR-136-001 (never negative / garbage output for skewed clocks)."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    dt = now + timedelta(minutes=5)
    assert formatting.humanize_elapsed(dt, now=now) == "just now"


def test_humanize_elapsed_default_now_does_not_raise():
    """Smoke test: not passing ``now`` must fall through to the live clock
    without raising. Does not assert an exact string — the exact value depends
    on the moment the test runs."""
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = formatting.humanize_elapsed(dt)
    assert isinstance(result, str)
    assert len(result) > 0


# ── pr_opened_at (A2 pin) ─────────────────────────────────────────


def test_pr_opened_at_prefers_raw_created_at_over_occurred_at():
    """A2 pin: occurred_at tracks updated_at and must not be used for the
    elapsed display when raw['created_at'] is present."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    row = _pr_row(
        requested_reviewers=[{"id": "1"}],
        occurred_at=now,
        created_at=(now - timedelta(days=9)).isoformat().replace("+00:00", "Z"),
    )
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    assert decision["waiting_since"] == "9 d"


def test_pr_decision_naive_created_at_is_not_dropped():
    """A raw['created_at'] without a UTC offset parses naive; it must be
    assumed UTC, not raise TypeError against the aware `now` and get the
    row silently dropped by _project_all."""
    row = _pr_row(
        requested_reviewers=[{"id": "1"}],
        created_at="2026-09-01T00:00:00",
    )
    decisions = projections.derive_decisions_from_github([row], github_user_id="1")
    assert len(decisions) == 1
    assert decisions[0]["waiting_since"].endswith("d")


def test_pr_opened_at_falls_back_to_occurred_at_when_created_at_missing():
    now = datetime.now(timezone.utc)
    row = _pr_row(requested_reviewers=[{"id": "1"}], occurred_at=now)
    assert rows.pr_opened_at(row) == now


# ── is_actionable_pr / project_pr_decision (A1) ──────────────────
# REQ: BR-136-001, FR-136-003


def test_project_pr_decision_reviewer_match():
    row = _pr_row(requested_reviewers=[{"id": "1"}, {"id": "2"}])
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    assert decision["context"] == "Waiting on your review"
    assert decision["source"] == "github"


def test_project_pr_decision_author_match_empty_reviewers():
    row = _pr_row(requested_reviewers=[], author_id="1")
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    assert decision["context"] == "Open PR awaiting your merge decision"


def test_project_pr_decision_author_with_nonempty_reviewers_is_not_actionable():
    """A1 pin: distinguishes the amended rule from the SDD's original rule.
    An open PR authored by the user with an outstanding review request for
    someone else is not the user's decision — it must be dropped."""
    row = _pr_row(requested_reviewers=[{"id": "2"}], author_id="1")
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_github_user_id_none():
    """REQ: FR-136-003 — github_user_id None returns None unconditionally."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])
    assert projections.project_pr_decision(row, github_user_id=None) is None


def test_project_pr_decision_draft_dropped():
    row = _pr_row(draft=True, requested_reviewers=[{"id": "1"}])
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_closed_dropped():
    row = _pr_row(state="closed", requested_reviewers=[{"id": "1"}])
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_merged_state_dropped():
    """'merged' is not a value GitHub returns in raw.state, but a defensive
    guard: any non-'open' state must drop the row."""
    row = _pr_row(state="merged", requested_reviewers=[{"id": "1"}])
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_missing_requested_reviewers_no_raise():
    """REQ: FR-136-003 — requested_reviewers key missing entirely -> None, no KeyError."""
    row = _pr_row(requested_reviewers=None, author_id="1")
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_scalar_requested_reviewers_no_raise():
    """REQ: FR-136-003 — non-list requested_reviewers -> None, no exception."""
    row = _pr_row(author_id="1")
    row.raw["requested_reviewers"] = "not-a-list"
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_list_of_strings_reviewers_no_raise():
    """REQ: FR-136-003 — list of plain strings (not dicts) -> None, no exception."""
    row = _pr_row(requested_reviewers=["alice", "bob"], author_id="1")
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_occurred_at_none_and_no_created_at():
    row = SimpleNamespace(
        id=uuid.uuid4(),
        raw={
            "number": 1,
            "title": "x",
            "state": "open",
            "draft": False,
            "user": {"id": "1"},
            "requested_reviewers": [{"id": "1"}],
        },
        occurred_at=None,
        provider_id="owner/repo#1",
        kind="pr",
    )
    assert projections.project_pr_decision(row, github_user_id="1") is None


def test_project_pr_decision_title_truncation():
    row = _pr_row(title="x" * 200, requested_reviewers=[{"id": "1"}])
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    assert len(decision["title"]) <= 120


def test_project_pr_decision_id_equals_str_row_id():
    """REQ: FR-136-006 — DecisionDict.id must equal str(row.id)."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    assert decision["id"] == str(row.id)


def test_project_pr_decision_all_five_fields_present():
    """REQ: BR-136-001 — response includes id, title, context, source, waiting_since."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    for field in ("id", "title", "context", "source", "waiting_since"):
        assert field in decision, f"DecisionDict missing field: {field}"
    assert decision["source"] == "github"


# ── derive_decisions_from_github ───────────────────────────────────
# REQ: FR-136-007, BR-136-003


def test_derive_decisions_from_github_three_actionable_rows():
    """Three well-formed, actionable rows -> three results (list of DecisionDicts)."""
    row1 = _pr_row(requested_reviewers=[{"id": "1"}], number=1)
    row2 = _pr_row(requested_reviewers=[{"id": "1"}], number=2)
    row3 = _pr_row(requested_reviewers=[], author_id="1", number=3)
    decisions = projections.derive_decisions_from_github(
        [row1, row2, row3], github_user_id="1"
    )
    assert len(decisions) == 3


def test_derive_decisions_from_github_skips_malformed_row():
    """REQ: BR-136-003 — one malformed row among good rows -> good rows returned,
    malformed row skipped, no exception propagates."""
    good1 = _pr_row(requested_reviewers=[{"id": "1"}])
    good2 = _pr_row(requested_reviewers=[], author_id="1")
    bad = SimpleNamespace(
        id=uuid.uuid4(), raw=[], occurred_at=datetime.now(timezone.utc)
    )
    decisions = projections.derive_decisions_from_github(
        [good1, good2, bad], github_user_id="1"
    )
    assert len(decisions) == 2


def test_derive_decisions_from_github_empty_input_returns_empty_list():
    """REQ: BR-136-003 — empty input list returns [] not None.
    Caller (_live_or_seed) checks truthiness to decide on fallback."""
    result = projections.derive_decisions_from_github([], github_user_id="1")
    assert result == []
    assert isinstance(result, list)


def test_derive_decisions_from_github_all_filtered_returns_empty_list():
    """REQ: BR-136-003 — when every row is filtered out (all drafts) the
    result is an empty list, not None or an exception."""
    draft1 = _pr_row(draft=True, requested_reviewers=[{"id": "1"}])
    draft2 = _pr_row(draft=True, requested_reviewers=[{"id": "1"}])
    result = projections.derive_decisions_from_github(
        [draft1, draft2], github_user_id="1"
    )
    assert result == []
    assert isinstance(result, list)


def test_derive_decisions_github_user_id_none_returns_empty_list():
    """REQ: FR-136-007 — github_user_id=None propagates through every row
    projection returning None -> empty list result."""
    row1 = _pr_row(requested_reviewers=[{"id": "1"}])
    row2 = _pr_row(requested_reviewers=[], author_id="1")
    result = projections.derive_decisions_from_github([row1, row2], github_user_id=None)
    assert result == []


# ── schema lock-step (FR-136-006, BR-136-005) ──────────────────────


def test_decision_dict_schema_round_trip_has_waiting_since_alias():
    """REQ: BR-136-005, FR-136-006 — DecisionDict round-trips through
    DecisionResponse; aliased key 'waitingSince' (camelCase) must be present."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    dumped = DecisionResponse.model_validate(decision).model_dump(by_alias=True)
    assert "waitingSince" in dumped


def test_decision_response_validates_github_source_literal():
    """REQ: BR-136-005 — source='github' is accepted by DecisionResponse's Literal.
    The four other variants (gmail, notion, linear, slack, calendar) need not be
    exercised by this feature; only 'github' is produced by the current projectors."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])
    decision = projections.project_pr_decision(row, github_user_id="1")
    assert decision is not None
    validated = DecisionResponse.model_validate(decision)
    assert validated.source == "github"


def test_decision_response_all_five_fields_survive_round_trip():
    """REQ: BR-136-005 — all 5 DecisionDict fields pass model_validate without
    ValidationError, confirming TypedDict and schema are in lock-step."""
    row = _pr_row(
        requested_reviewers=[{"id": "42"}],
        number=99,
        title="Ship this feature",
    )
    decision = projections.project_pr_decision(row, github_user_id="42")
    assert decision is not None
    validated = DecisionResponse.model_validate(decision)
    dumped = validated.model_dump()
    assert dumped["id"] == str(row.id)
    assert "#99 Ship this feature" in dumped["title"]
    assert dumped["context"] == "Waiting on your review"
    assert dumped["source"] == "github"
    assert isinstance(dumped["waiting_since"], str)
