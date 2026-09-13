"""Route-level tests for GET /api/v1/dashboard/agent-activity (FEAT-136).

Monkeypatches ``queries.fetch_github_activity_by_kind`` (kind='pr') and
``dashboard_module._fetch_all`` rather than standing up a real database.

``test_dashboard_derivation.py`` already characterises
``derive_activities_from_github`` in isolation; this file exercises what
only shows up once rows flow through the actual route: the live/seed mode
switch, derivation-raises fallback, personalization call-through, and
the auth gate.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import src.api.v1.dashboard as dashboard_module
from httpx import ASGITransport, AsyncClient
from src.main import app


def _pr_row(
    *,
    number=7,
    title="Fix the widget",
    provider_id="owner/repo#7",
    occurred_at=None,
):
    raw = {"number": number, "title": title}
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw=raw,
        occurred_at=occurred_at or datetime(2026, 9, 12, tzinfo=timezone.utc),
        provider_id=provider_id,
        kind="pr",
    )


def _seed_tick():
    return SimpleNamespace(
        id="seed-tick-1",
        agent="core",
        message="Seed activity",
        time="5 m ago",
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


@pytest.fixture(autouse=True)
def _fake_seed_fetch(monkeypatch):
    """Patch _fetch_all so seed-table reads return a predictable row."""

    async def _fake_fetch_all(db, stmt):
        return [_seed_tick()]

    monkeypatch.setattr(dashboard_module, "_fetch_all", _fake_fetch_all)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_path_returns_derived_rows(monkeypatch):
    """Live GitHub PR rows are returned with mode='live'; response contains
    all required fields."""
    row = _pr_row(number=12, title="Deploy pipeline", provider_id="acme/widgets#12")

    async def _fake_prs(db, user_id, kind, **kwargs):
        return [row]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/agent-activity")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "live"
    assert body["total"] == 1
    assert body["data"][0]["agent"] == "widgets"
    assert body["data"][0]["message"] == "#12 Deploy pipeline"


# ---------------------------------------------------------------------------
# Response envelope shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_response_envelope_has_data_total_mode(monkeypatch):
    """Live mode response always includes data (list), total (int), mode='live'."""
    row = _pr_row(provider_id="acme/core#3")

    async def _fake_prs(db, user_id, kind, **kwargs):
        return [row]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/agent-activity")

    body = resp.json()
    assert "data" in body
    assert "total" in body
    assert "mode" in body
    assert isinstance(body["data"], list)
    assert isinstance(body["total"], int)
    assert body["total"] == len(body["data"])
    assert body["mode"] == "live"


@pytest.mark.asyncio
async def test_seed_response_envelope_has_data_total_mode(monkeypatch):
    """Seed mode response always includes data, total, mode; total == len(data)."""

    async def _fake_prs(db, user_id, kind, **kwargs):
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/agent-activity")

    body = resp.json()
    assert "data" in body
    assert "total" in body
    assert "mode" in body
    assert isinstance(body["data"], list)
    assert isinstance(body["total"], int)
    assert body["total"] == len(body["data"])
    assert body["mode"] == "seed"


# ---------------------------------------------------------------------------
# Seed fallback: no ingested PRs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_ingested_prs_falls_back_to_seed(monkeypatch):
    """Empty live_rows triggers seed fallback with mode='seed'."""

    async def _fake_prs(db, user_id, kind, **kwargs):
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/agent-activity")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "seed"
    assert body["total"] == 1
    assert body["data"][0]["id"] == "seed-tick-1"


# ---------------------------------------------------------------------------
# Seed fallback: derivation raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derivation_raises_falls_back_to_seed(monkeypatch, caplog):
    """Derivation exception triggers seed fallback with warning log;
    response is still HTTP 200 and well-formed."""
    row = _pr_row()

    async def _fake_prs(db, user_id, kind, **kwargs):
        return [row]

    def _boom(rows):
        raise RuntimeError("derivation blew up")

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )
    monkeypatch.setattr(dashboard_module.derive, "derive_activities_from_github", _boom)

    with caplog.at_level(logging.WARNING, logger="src.api.v1.dashboard"):
        async with await _client() as client:
            resp = await client.get("/api/v1/dashboard/agent-activity")

    assert resp.status_code == 200
    assert resp.json()["mode"] == "seed"
    assert "derivation failed" in " ".join(caplog.messages)


# ---------------------------------------------------------------------------
# Personalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personalization_user_id_passed_to_query(monkeypatch, _fake_user):
    """The route must pass current_user.id to fetch_github_activity_by_kind
    so each user only sees their own ingested rows."""
    captured_user_ids: list[uuid.UUID] = []

    async def _fake_prs(db, user_id, kind, **kwargs):
        captured_user_ids.append(user_id)
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        await client.get("/api/v1/dashboard/agent-activity")

    assert len(captured_user_ids) == 1
    assert captured_user_ids[0] == _fake_user.id


@pytest.mark.asyncio
async def test_query_called_with_pr_kind(monkeypatch):
    """The agent-activity route must query kind='pr', not 'issue'."""
    captured_kinds: list[str] = []

    async def _fake_prs(db, user_id, kind, **kwargs):
        captured_kinds.append(kind)
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        await client.get("/api/v1/dashboard/agent-activity")

    assert captured_kinds == ["pr"]


# ---------------------------------------------------------------------------
# Unauthenticated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_requires_auth():
    """Unauthenticated request must return 401."""
    from src.auth.dependencies import get_current_user

    app.dependency_overrides.pop(get_current_user, None)

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/agent-activity")

    assert resp.status_code == 401
