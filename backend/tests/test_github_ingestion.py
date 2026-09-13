"""Regression tests for FEAT-139 — GitHub ingestion write path.

The mock boundary is the tool layer (GitHubListIssues / GitHubListPrs),
never httpx and never a real Postgres connection. ``FakeSession`` below
simulates the ``ON CONFLICT (user_id, kind, provider_id) DO UPDATE``
upsert against an in-memory table by reading the row dicts straight off
the ``Insert`` statement's ``_multi_values`` (exactly what
``pg_insert(...).values(rows)`` was called with) — this lets tests
assert on observable rows/derived state rather than on internal call
counts, without standing up a real database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from src.services.dashboard.projections import project_github_activity
from src.services.ingestion.github import ingest
from src.services.ingestion.runner import IngestionError
from src.tools.base import ToolError


class FakeSession:
    """In-memory stand-in for AsyncSession's role in ingest().

    Keyed exactly like the real unique constraint: (user_id, kind,
    provider_id). commit()/rollback() are tracked so a per-repo failure
    can be asserted to have rolled back cleanly.
    """

    def __init__(self) -> None:
        self.table: dict[tuple[str, str, str], SimpleNamespace] = {}
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt) -> None:
        raw_rows = stmt._multi_values[0] if stmt._multi_values else []
        rows = [{col.name: value for col, value in row.items()} for row in raw_rows]
        for row in rows:
            key = (str(row["user_id"]), row["kind"], row["provider_id"])
            self.table[key] = SimpleNamespace(
                id=self.table[key].id if key in self.table else uuid.uuid4(),
                user_id=row["user_id"],
                kind=row["kind"],
                provider_id=row["provider_id"],
                raw=row["raw"],
                occurred_at=row["occurred_at"],
                ingested_at=datetime.now(timezone.utc),
            )

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _issue_output(items):
    return SimpleNamespace(data=items)


def _pr_output(items):
    return SimpleNamespace(data=items)


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _pr_item(
    number, *, state="open", merged_at=None, updated_at="2026-09-01T00:00:00Z"
):
    return {
        "number": number,
        "title": f"PR {number}",
        "html_url": f"https://github.com/o/r/pull/{number}",
        "state": state,
        "merged_at": merged_at,
        "updated_at": updated_at,
        "user": {"login": "arshad"},
    }


@pytest.fixture(autouse=True)
def _no_event_bus(monkeypatch):
    monkeypatch.setattr(
        "src.services.ingestion.github.event_bus.publish", AsyncMock(return_value=0)
    )


def _patch_tools(
    monkeypatch, *, issues_by_repo=None, prs_by_repo=None, raises_for=None
):
    """Patch GitHubListIssues/GitHubListPrs so ingest() never touches httpx.

    ``raises_for`` maps repo -> exception to raise instead of returning data.
    """
    issues_by_repo = issues_by_repo or {}
    prs_by_repo = prs_by_repo or {}
    raises_for = raises_for or {}

    class _FakeIssues:
        async def __call__(self, *, user, db, payload):
            if payload.repo in raises_for:
                raise raises_for[payload.repo]
            return _issue_output(issues_by_repo.get(payload.repo, []))

    class _FakePrs:
        async def __call__(self, *, user, db, payload):
            if payload.repo in raises_for:
                raise raises_for[payload.repo]
            return _pr_output(prs_by_repo.get(payload.repo, []))

    monkeypatch.setattr(
        "src.services.ingestion.github.GitHubListIssues", lambda: _FakeIssues()
    )
    monkeypatch.setattr(
        "src.services.ingestion.github.GitHubListPrs", lambda: _FakePrs()
    )


# ── P0-1: terminal-state reconciliation ──────────────────────────────


@pytest.mark.asyncio
async def test_merged_pr_state_reconciliation(monkeypatch):
    user = _user()
    db = FakeSession()

    _patch_tools(
        monkeypatch,
        prs_by_repo={"o/r": [_pr_item(1, state="open")]},
    )
    await ingest(user=user, db=db, payload={"repos": ["o/r"]})

    key = (str(user.id), "pr", "o/r#1")
    assert project_github_activity(db.table[key])["state"] == "open"

    _patch_tools(
        monkeypatch,
        prs_by_repo={
            "o/r": [
                _pr_item(
                    1,
                    state="closed",
                    merged_at="2026-09-02T00:00:00Z",
                    updated_at="2026-09-02T00:00:00Z",
                )
            ]
        },
    )
    await ingest(user=user, db=db, payload={"repos": ["o/r"]})

    result = project_github_activity(db.table[key])
    assert result["state"] == "merged"


@pytest.mark.asyncio
async def test_always_requests_state_all(monkeypatch):
    seen_states: list[str] = []

    class _RecordingIssues:
        async def __call__(self, *, user, db, payload):
            seen_states.append(payload.state)
            return _issue_output([])

    class _RecordingPrs:
        async def __call__(self, *, user, db, payload):
            seen_states.append(payload.state)
            return _pr_output([])

    monkeypatch.setattr(
        "src.services.ingestion.github.GitHubListIssues", lambda: _RecordingIssues()
    )
    monkeypatch.setattr(
        "src.services.ingestion.github.GitHubListPrs", lambda: _RecordingPrs()
    )

    await ingest(user=_user(), db=FakeSession(), payload={"repos": ["o/r"]})
    await ingest(
        user=_user(), db=FakeSession(), payload={"repos": ["o/r"], "full_refresh": True}
    )

    assert seen_states == ["all", "all", "all", "all"]


# ── P0-2: per-repo transaction isolation ─────────────────────────────


@pytest.mark.asyncio
async def test_per_repo_isolation(monkeypatch):
    user = _user()
    db = FakeSession()

    _patch_tools(
        monkeypatch,
        prs_by_repo={"good/repo": [_pr_item(1)]},
        raises_for={"bad/repo": ToolError("github_forbidden", "nope")},
    )

    result = await ingest(
        user=user, db=db, payload={"repos": ["bad/repo", "good/repo"]}
    )

    assert result["status"] == "partial"
    assert result["failed_repos"] == [
        {"repo": "bad/repo", "code": "github_forbidden", "message": "nope"}
    ]
    assert (str(user.id), "pr", "good/repo#1") in db.table
    assert db.rollbacks == 1
    assert db.commits == 1


@pytest.mark.asyncio
async def test_transport_error_isolated_to_its_repo(monkeypatch):
    """A read timeout is a per-repo failure, not a run-ending one.

    The GitHub client only maps HTTP status codes to ToolError, so a
    transport failure surfaces as a raw httpx error; if it escaped the
    loop every repo queued after the slow one would be skipped.
    """
    user = _user()
    db = FakeSession()

    _patch_tools(
        monkeypatch,
        prs_by_repo={"good/repo": [_pr_item(1)]},
        raises_for={"slow/repo": httpx.ReadTimeout("timed out")},
    )

    result = await ingest(
        user=user, db=db, payload={"repos": ["slow/repo", "good/repo"]}
    )

    assert result["status"] == "partial"
    assert result["failed_repos"][0]["repo"] == "slow/repo"
    assert result["failed_repos"][0]["code"] == "github_ingest_provider_unreachable"
    assert (str(user.id), "pr", "good/repo#1") in db.table


@pytest.mark.asyncio
async def test_all_repos_failed_raises(monkeypatch):
    user = _user()
    db = FakeSession()

    _patch_tools(
        monkeypatch,
        raises_for={
            "a/a": ToolError("provider_request_failed", "boom"),
            "b/b": ToolError("provider_request_failed", "boom"),
        },
    )

    with pytest.raises(IngestionError):
        await ingest(user=user, db=db, payload={"repos": ["a/a", "b/b"]})


# ── P0-3: timestamp ordering poisoning ────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_updated_at_skipped(monkeypatch):
    user = _user()
    db = FakeSession()

    _patch_tools(
        monkeypatch,
        prs_by_repo={
            "o/r": [
                _pr_item(1, updated_at=None),
                _pr_item(2, updated_at="not-a-date"),
                _pr_item(3, updated_at="2026-09-01T00:00:00Z"),
            ]
        },
    )

    result = await ingest(user=user, db=db, payload={"repos": ["o/r"]})

    assert result["skipped_count"] == 2
    assert (str(user.id), "pr", "o/r#1") not in db.table
    assert (str(user.id), "pr", "o/r#2") not in db.table
    assert (str(user.id), "pr", "o/r#3") in db.table


# ── AC5: idempotency ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency(monkeypatch):
    user = _user()
    db = FakeSession()

    _patch_tools(monkeypatch, prs_by_repo={"o/r": [_pr_item(1)]})

    await ingest(user=user, db=db, payload={"repos": ["o/r"]})
    first_ingested_at = db.table[(str(user.id), "pr", "o/r#1")].ingested_at

    await ingest(user=user, db=db, payload={"repos": ["o/r"]})
    second_ingested_at = db.table[(str(user.id), "pr", "o/r#1")].ingested_at

    assert len(db.table) == 1
    assert second_ingested_at >= first_ingested_at


@pytest.mark.asyncio
async def test_full_refresh_ignores_watermark_and_still_reconciles(monkeypatch):
    """full_refresh no longer changes the state filter; it's still a no-op
    flag accepted for backward compatibility, and ingestion still picks up
    a terminal-state change regardless of the flag."""
    user = _user()
    db = FakeSession()

    _patch_tools(monkeypatch, prs_by_repo={"o/r": [_pr_item(1, state="open")]})
    await ingest(user=user, db=db, payload={"repos": ["o/r"]})

    _patch_tools(
        monkeypatch,
        prs_by_repo={
            "o/r": [
                _pr_item(
                    1,
                    state="closed",
                    updated_at="2026-09-03T00:00:00Z",
                )
            ]
        },
    )
    result = await ingest(
        user=user, db=db, payload={"repos": ["o/r"], "full_refresh": True}
    )

    assert result["status"] == "ok"
    key = (str(user.id), "pr", "o/r#1")
    assert project_github_activity(db.table[key])["state"] == "closed"


# ── payload validation (unchanged) ────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_repos_raises():
    with pytest.raises(IngestionError):
        await ingest(user=_user(), db=FakeSession(), payload={"repos": []})


# ── silent-failure-hunter regressions ──────────────────────────────────


@pytest.mark.asyncio
async def test_non_string_updated_at_isolated_not_crashed(monkeypatch):
    """A non-string updated_at (malformed body) is skipped like any other
    unparseable timestamp — it must not raise TypeError out of the mapper
    and abort every repo in the run, only this one item.
    """
    user = _user()
    db = FakeSession()

    _patch_tools(
        monkeypatch,
        prs_by_repo={
            "o/r": [
                _pr_item(1, updated_at=12345),
                _pr_item(2, updated_at="2026-09-01T00:00:00Z"),
            ]
        },
    )

    result = await ingest(user=user, db=db, payload={"repos": ["o/r"]})

    assert result["status"] == "ok"
    assert result["skipped_count"] == 1
    assert (str(user.id), "pr", "o/r#1") not in db.table
    assert (str(user.id), "pr", "o/r#2") in db.table


@pytest.mark.asyncio
async def test_event_publish_failure_does_not_discard_committed_result(monkeypatch):
    """A best-effort Redis publish failure must not turn an already-
    committed, already-correct ingestion result into a raised exception —
    matching the guard already applied to this same call in obsidian.py.
    """
    user = _user()
    db = FakeSession()

    _patch_tools(monkeypatch, prs_by_repo={"o/r": [_pr_item(1)]})
    monkeypatch.setattr(
        "src.services.ingestion.github.event_bus.publish",
        AsyncMock(side_effect=ConnectionError("redis unreachable")),
    )

    result = await ingest(user=user, db=db, payload={"repos": ["o/r"]})

    assert result["status"] == "ok"
    assert (str(user.id), "pr", "o/r#1") in db.table


@pytest.mark.asyncio
async def test_unclassified_repo_failure_rolls_back_before_reraising(monkeypatch):
    """An exception type the failure-policy table doesn't recognise still
    must not leave this repo's transaction dangling on the session before
    it propagates out of ingest().
    """
    user = _user()
    db = FakeSession()

    _patch_tools(
        monkeypatch,
        raises_for={"o/r": RuntimeError("unexpected")},
    )

    with pytest.raises(RuntimeError):
        await ingest(user=user, db=db, payload={"repos": ["o/r"]})

    assert db.rollbacks == 1


# ── batch-size clamp (config ↔ tool-schema contract) ───────────────────


def _record_max_results(monkeypatch) -> list[int]:
    """Patch both list tools to capture the max_results they were handed."""
    seen: list[int] = []

    class _Recording:
        def __init__(self, output):
            self._output = output

        async def __call__(self, *, user, db, payload):
            seen.append(payload.max_results)
            return self._output

    monkeypatch.setattr(
        "src.services.ingestion.github.GitHubListIssues",
        lambda: _Recording(_issue_output([])),
    )
    monkeypatch.setattr(
        "src.services.ingestion.github.GitHubListPrs",
        lambda: _Recording(_pr_output([])),
    )
    return seen


@pytest.mark.asyncio
async def test_batch_size_above_tool_limit_is_clamped_not_fatal(monkeypatch):
    """MAX_INGEST_BATCH_SIZE is shared with the calendar/email runners,
    whose tools accept a different maximum, so an operator can legitimately
    set it above what the GitHub list tools allow.

    Previously that raised a Pydantic ValidationError while *building* the
    tool input — before any per-repo except clause could see it — so it
    escaped ingest() uncaught and took down every repo at once rather than
    degrading. It must instead clamp to the tools' own declared bound.
    """
    monkeypatch.setenv("MAX_INGEST_BATCH_SIZE", "5000")
    seen = _record_max_results(monkeypatch)

    result = await ingest(
        user=_user(), db=FakeSession(), payload={"repos": ["o/a", "o/b"]}
    )

    assert result["status"] == "ok"
    assert result["failed_repos"] == []
    # Both repos × both tools were actually called — i.e. the run really
    # proceeded rather than failing early.
    assert len(seen) == 4
    assert seen == [100, 100, 100, 100]


@pytest.mark.asyncio
async def test_batch_size_below_tool_limit_is_passed_through(monkeypatch):
    """The clamp is a ceiling only — it must not override a smaller
    operator-configured batch size."""
    monkeypatch.setenv("MAX_INGEST_BATCH_SIZE", "7")
    seen = _record_max_results(monkeypatch)

    await ingest(user=_user(), db=FakeSession(), payload={"repos": ["o/a"]})

    assert seen == [7, 7]
