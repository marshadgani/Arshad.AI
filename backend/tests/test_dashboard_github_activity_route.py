"""Route- and query-layer tests for GET /api/v1/dashboard/github-activity.

test_dashboard_github_activity.py already characterises
``project_github_activity`` (the pure JSONB->dict projection) plus the bare
401 path. That leaves the parts of FEAT-139's acceptance criteria that only
show up once rows flow through the actual route and query layer:

  * the route returns a real 200 envelope with camelCase aliases
  * a mix of valid/invalid `kind` rows is filtered correctly end to end
  * an empty ingestion table is a truthful 200, not a 404/500
  * ``fetch_recent_github_activity`` orders by occurred_at DESC, applies
    GITHUB_ACTIVITY_LIMIT, and filters by the caller's user_id (so one
    user's dashboard never reads another user's GitHub activity)

Follows the module-patch style already used in test_finance_endpoints.py
(monkeypatch the collaborator function directly) rather than standing up a
real database — per .claude/rules/subagent-verification.md, every
collaborator path referenced below was confirmed to exist by direct Read
before writing these tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import src.api.v1.dashboard as dashboard_module
from httpx import ASGITransport, AsyncClient
from src.main import app
from src.services.dashboard.queries import GITHUB_ACTIVITY_LIMIT


def _row(*, kind="issue", provider_id="owner/repo#42", raw=None, occurred_at=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind=kind,
        provider_id=provider_id,
        raw=raw if raw is not None else {},
        occurred_at=occurred_at or datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def _fake_user():
    fake_user = SimpleNamespace(id=uuid.uuid4())

    async def _get_current_user():
        return fake_user

    from src.auth.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = _get_current_user
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Route: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_returns_200_envelope_with_camelcase_aliases(monkeypatch):
    row = _row(
        kind="pr",
        provider_id="owner/repo#7",
        raw={
            "title": "Add feature",
            "html_url": "https://github.com/owner/repo/pull/7",
            "state": "open",
            "draft": True,
            "user": {"login": "arshad"},
        },
    )

    async def _fake_fetch(db, user_id, **kwargs):
        return [row]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_recent_github_activity", _fake_fetch
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/github-activity")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["data"][0]

    # camelCase aliases, not the python-side snake_case names
    assert "isDraft" in item and item["isDraft"] is True
    assert "updatedAt" in item
    assert "is_draft" not in item
    assert "updated_at" not in item
    assert item["kind"] == "pr"
    assert item["repository"] == "owner/repo"
    assert item["number"] == 7


@pytest.mark.asyncio
async def test_route_empty_table_returns_200_not_404(monkeypatch):
    async def _fake_fetch(db, user_id, **kwargs):
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_recent_github_activity", _fake_fetch
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/github-activity")

    assert resp.status_code == 200
    assert resp.json() == {"data": [], "total": 0}


# ---------------------------------------------------------------------------
# Route: mixed valid/invalid kind rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_excludes_unrecognised_kind_rows(monkeypatch, caplog):
    valid = _row(kind="issue", provider_id="o/r#1", raw={"title": "valid"})
    bad = _row(kind="commit", provider_id="o/r#2", raw={"title": "bad kind"})

    async def _fake_fetch(db, user_id, **kwargs):
        return [valid, bad]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_recent_github_activity", _fake_fetch
    )

    import logging

    with caplog.at_level(logging.INFO, logger="src.api.v1.dashboard"):
        async with await _client() as client:
            resp = await client.get("/api/v1/dashboard/github-activity")

    body = resp.json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert body["data"][0]["id"] == str(valid.id)
    assert "skipped=1" in " ".join(caplog.messages)


# ---------------------------------------------------------------------------
# Route: a DB-layer failure must surface as 500, not be swallowed as empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_propagates_query_layer_exception(monkeypatch):
    async def _boom(db, user_id, **kwargs):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(dashboard_module.queries, "fetch_recent_github_activity", _boom)

    async with await _client() as client:
        with pytest.raises(RuntimeError):
            await client.get("/api/v1/dashboard/github-activity")


# ---------------------------------------------------------------------------
# Route: unauthenticated request is rejected before the handler runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_requires_auth():
    from src.auth.dependencies import get_current_user

    app.dependency_overrides.pop(get_current_user, None)

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/github-activity")

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Query layer: fetch_recent_github_activity — order, limit, user filter
# ---------------------------------------------------------------------------


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult()


@pytest.mark.asyncio
async def test_query_orders_desc_limits_and_filters_by_user():
    from src.services.dashboard.queries import fetch_recent_github_activity

    session = _FakeSession()
    user_id = uuid.uuid4()

    await fetch_recent_github_activity(session, user_id)

    assert len(session.statements) == 1
    sql = str(
        session.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()

    assert "order by" in sql and "occurred_at" in sql and "desc" in sql
    assert f"limit {GITHUB_ACTIVITY_LIMIT}" in sql
    assert "user_id" in sql
    assert user_id.hex in sql.replace("-", "")


@pytest.mark.asyncio
async def test_query_respects_explicit_limit_override():
    from src.services.dashboard.queries import fetch_recent_github_activity

    session = _FakeSession()
    await fetch_recent_github_activity(session, uuid.uuid4(), limit=3)

    sql = str(
        session.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "limit 3" in sql
