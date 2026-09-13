"""Route-level tests for GET /api/v1/dashboard/tasks (FEAT-136).

Monkeypatches ``queries.fetch_flagged_gmail_threads`` and
``dashboard_module._fetch_all`` rather than standing up a real database.

``test_dashboard_derivation.py`` already characterises
``derive_tasks_from_gmail`` in isolation; this file exercises what only
shows up once rows flow through the actual route: the live/seed mode
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


def _gmail_row(
    *,
    subject="Review this PR",
    snippet="fallback",
    labels=None,
    occurred_at=None,
):
    raw: dict = {"snippet": snippet}
    derived: dict = {}
    if labels is not None:
        derived["labels"] = labels
    if subject is not None:
        derived["subject"] = subject
    if derived:
        raw["_derived"] = derived
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw=raw,
        occurred_at=occurred_at or datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def _seed_task():
    return SimpleNamespace(
        id="seed-task-1",
        title="Seed task",
        source="gmail",
        due="Today 09:00",
        priority="p2",
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
        return [_seed_task()]

    monkeypatch.setattr(dashboard_module, "_fetch_all", _fake_fetch_all)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_path_returns_derived_rows(monkeypatch):
    """REQ: BR-136-001 — live Gmail threads are returned with mode='live';
    response contains all required fields."""
    row = _gmail_row(labels=["STARRED"], subject="Sign this contract")

    async def _fake_gmail(db, user_id, **kwargs):
        return [row]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _fake_gmail
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/tasks")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "live"
    assert body["total"] == 1
    assert body["data"][0]["title"] == "Sign this contract"
    assert body["data"][0]["source"] == "gmail"


# ---------------------------------------------------------------------------
# Response envelope shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_response_envelope_has_data_total_mode(monkeypatch):
    """Live mode response always includes data (list), total (int), mode='live'."""
    row = _gmail_row(labels=["IMPORTANT"], subject="Approve invoice")

    async def _fake_gmail(db, user_id, **kwargs):
        return [row]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _fake_gmail
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/tasks")

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

    async def _fake_gmail(db, user_id, **kwargs):
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _fake_gmail
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/tasks")

    body = resp.json()
    assert "data" in body
    assert "total" in body
    assert "mode" in body
    assert isinstance(body["data"], list)
    assert isinstance(body["total"], int)
    assert body["total"] == len(body["data"])
    assert body["mode"] == "seed"


# ---------------------------------------------------------------------------
# Seed fallback: no ingested threads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_ingested_threads_falls_back_to_seed(monkeypatch):
    """Empty live_rows triggers seed fallback with mode='seed'."""

    async def _fake_gmail(db, user_id, **kwargs):
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _fake_gmail
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/tasks")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "seed"
    assert body["total"] == 1
    assert body["data"][0]["id"] == "seed-task-1"


# ---------------------------------------------------------------------------
# Seed fallback: derivation raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derivation_raises_falls_back_to_seed(monkeypatch, caplog):
    """Derivation exception triggers seed fallback with warning log;
    response is still HTTP 200 and well-formed."""
    row = _gmail_row(labels=["STARRED"])

    async def _fake_gmail(db, user_id, **kwargs):
        return [row]

    def _boom(rows):
        raise RuntimeError("derivation blew up")

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _fake_gmail
    )
    monkeypatch.setattr(dashboard_module.derive, "derive_tasks_from_gmail", _boom)

    with caplog.at_level(logging.WARNING, logger="src.api.v1.dashboard"):
        async with await _client() as client:
            resp = await client.get("/api/v1/dashboard/tasks")

    assert resp.status_code == 200
    assert resp.json()["mode"] == "seed"
    assert "derivation failed" in " ".join(caplog.messages)


# ---------------------------------------------------------------------------
# Personalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personalization_user_id_passed_to_query(monkeypatch, _fake_user):
    """The route must pass current_user.id to fetch_flagged_gmail_threads
    so each user only sees their own ingested rows."""
    captured_user_ids: list[uuid.UUID] = []

    async def _fake_gmail(db, user_id, **kwargs):
        captured_user_ids.append(user_id)
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _fake_gmail
    )

    async with await _client() as client:
        await client.get("/api/v1/dashboard/tasks")

    assert len(captured_user_ids) == 1
    assert captured_user_ids[0] == _fake_user.id


# ---------------------------------------------------------------------------
# Unauthenticated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_requires_auth():
    """Unauthenticated request must return 401."""
    from src.auth.dependencies import get_current_user

    app.dependency_overrides.pop(get_current_user, None)

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/tasks")

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Regression guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_fallback_returns_seed_row(monkeypatch):
    """Seed table is read-only. The autouse _fake_seed_fetch returns exactly
    1 row; this confirms the route propagates that count correctly."""

    async def _fake_gmail(db, user_id, **kwargs):
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _fake_gmail
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/tasks")

    body = resp.json()
    assert body["mode"] == "seed"
    assert body["total"] == 1
    assert body["data"][0]["id"] == "seed-task-1"
    assert body["data"][0]["title"] == "Seed task"
