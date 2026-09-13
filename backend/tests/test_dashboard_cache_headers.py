"""SEC regression: every dashboard response must be uncacheable.

The four hybrid widgets return personal data derived from the caller's own
Gmail subjects and GitHub PR/issue titles. They are plain authenticated
GETs with no validator, so without an explicit directive RFC 9111 permits
a shared cache to store and reuse them — which would serve one user's rows
to the next caller. ``api/v1/dashboard._no_store`` is a router-level
dependency precisely so a newly added route cannot forget it; these tests
pin that, including for the error paths (404 seed-singleton, 401 auth).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import src.api.v1.dashboard as dashboard_module
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user
from src.main import app

HYBRID_ROUTES = [
    "/api/v1/dashboard/tasks",
    "/api/v1/dashboard/decisions",
    "/api/v1/dashboard/notifications",
    "/api/v1/dashboard/agent-activity",
    "/api/v1/dashboard/github-activity",
]


@pytest.fixture(autouse=True)
def _fake_user():
    fake_user = SimpleNamespace(id=uuid.uuid4())

    async def _get_current_user():
        return fake_user

    app.dependency_overrides[get_current_user] = _get_current_user
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Stub every collaborator that would otherwise need a real session."""

    async def _empty_fetch_all(db, stmt):
        return []

    async def _empty_rows(db, user_id, *args, **kwargs):
        return []

    async def _no_github(db, user_id):
        return None

    monkeypatch.setattr(dashboard_module, "_fetch_all", _empty_fetch_all)
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_flagged_gmail_threads", _empty_rows
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _empty_rows
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_recent_github_activity", _empty_rows
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _no_github
    )


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("route", HYBRID_ROUTES)
@pytest.mark.asyncio
async def test_personal_data_routes_are_no_store(route):
    async with await _client() as client:
        resp = await client.get(route)

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_error_responses_are_not_covered_by_no_store():
    """Documents the boundary of the fix rather than over-claiming it.

    FastAPI builds error responses in an exception handler, using a fresh
    ``JSONResponse`` — the ``Response`` object ``_no_store`` mutated is
    discarded, so a 401/404 carries no Cache-Control. That is acceptable
    *because* those bodies are static error envelopes with no personal
    data in them. If a future error path ever starts echoing user content,
    this test failing is the signal that the directive must move to
    middleware instead of a dependency.
    """
    app.dependency_overrides.pop(get_current_user, None)

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/tasks")

    assert resp.status_code == 401
    assert "cache-control" not in resp.headers
    assert "gmail" not in resp.text.lower()
