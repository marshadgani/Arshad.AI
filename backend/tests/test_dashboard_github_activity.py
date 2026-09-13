"""Tests for FEAT-139 — GET /api/v1/dashboard/github-activity.

Pure-function characterisation tests for ``project_github_activity``
(SimpleNamespace stand-ins, no DB), plus an integration smoke test for the
route itself using dependency overrides, matching the pattern in
test_finance_endpoints.py.

The projection lives in ``services/dashboard/projections`` — the route
module holds no row-translation logic to import.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from src.main import app
from src.services.dashboard.projections import project_github_activity


def _row(*, kind="issue", provider_id="owner/repo#42", raw=None, occurred_at=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind=kind,
        provider_id=provider_id,
        raw=raw if raw is not None else {},
        occurred_at=occurred_at or datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


# ── project_github_activity ────────────────────────────────────────


def test_happy_path_issue():
    raw = {
        "title": "Fix the thing",
        "html_url": "https://github.com/owner/repo/issues/42",
        "number": 42,
        "state": "open",
        "user": {"login": "arshad"},
    }
    row = _row(kind="issue", raw=raw)

    result = project_github_activity(row)

    assert result == {
        "id": str(row.id),
        "title": "Fix the thing",
        "url": "https://github.com/owner/repo/issues/42",
        "number": 42,
        "repository": "owner/repo",
        "kind": "issue",
        "state": "open",
        "is_draft": False,
        "author": "arshad",
        "updated_at": row.occurred_at.isoformat(),
    }


def test_happy_path_pr_open():
    raw = {
        "title": "Add feature",
        "html_url": "https://github.com/o/r/pull/1",
        "state": "open",
    }
    row = _row(kind="pr", provider_id="o/r#1", raw=raw)

    result = project_github_activity(row)

    assert result["state"] == "open"
    assert result["is_draft"] is False


def test_pr_merged_at_wins_over_state():
    raw = {"title": "x", "state": "closed", "merged_at": "2026-09-01T00:00:00Z"}
    row = _row(kind="pr", raw=raw)

    result = project_github_activity(row)

    assert result["state"] == "merged"


def test_pr_draft_and_closed_is_not_conflated_with_draft_state():
    raw = {"title": "x", "state": "closed", "draft": True}
    row = _row(kind="pr", raw=raw)

    result = project_github_activity(row)

    assert result["state"] == "closed"
    assert result["is_draft"] is True


def test_raw_user_is_none_yields_no_author():
    raw = {"title": "x", "user": None}
    row = _row(raw=raw)

    result = project_github_activity(row)

    assert result["author"] is None


def test_user_present_without_login_yields_no_author():
    raw = {"title": "x", "user": {"id": 1}}
    row = _row(raw=raw)

    result = project_github_activity(row)

    assert result["author"] is None


def test_missing_html_url_yields_no_url():
    row = _row(raw={"title": "x"})

    result = project_github_activity(row)

    assert result["url"] is None


def test_non_https_url_is_rejected():
    row = _row(raw={"title": "x", "html_url": "javascript:alert(1)"})

    result = project_github_activity(row)

    assert result["url"] is None


def test_number_falls_back_to_provider_id_when_raw_number_absent():
    row = _row(provider_id="owner/repo#77", raw={"title": "x"})

    result = project_github_activity(row)

    assert result["number"] == 77
    assert result["repository"] == "owner/repo"


def test_provider_id_without_hash_uses_whole_string_as_repository():
    row = _row(provider_id="no-hash-here", raw={"title": "x"})

    result = project_github_activity(row)

    assert result["repository"] == "no-hash-here"
    assert result["number"] is None


def test_unrecognised_state_collapses_to_open():
    row = _row(raw={"title": "x", "state": "weird"})

    result = project_github_activity(row)

    assert result["state"] == "open"


def test_unrecognised_kind_returns_none():
    row = _row(kind="commit", raw={"title": "x"})

    assert project_github_activity(row) is None


def test_empty_raw_still_returns_a_dict_with_safe_defaults():
    row = _row(raw={})

    result = project_github_activity(row)

    assert result["title"] == "(untitled)"
    assert result["url"] is None
    assert result["author"] is None


# ── GET /api/v1/dashboard/github-activity ───────────────────────────


@pytest.fixture(autouse=True)
def _fake_user():
    fake_user = SimpleNamespace(id=uuid.uuid4())

    async def _get_current_user():
        return fake_user

    from src.auth.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = _get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_unauthenticated_returns_401():
    from src.auth.dependencies import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/github-activity")

    assert resp.status_code == 401
