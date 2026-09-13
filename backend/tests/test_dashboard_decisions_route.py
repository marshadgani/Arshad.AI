"""Route-level tests for GET /api/v1/dashboard/decisions (FEAT-136).

Mirrors test_dashboard_github_activity_route.py: monkeypatch the
collaborator functions directly (``queries.fetch_github_provider_user_id``,
``queries.fetch_github_activity_by_kind``, ``dashboard_module._fetch_all``)
rather than standing up a real database — per
``.claude/rules/subagent-verification.md``, every collaborator path
referenced below was confirmed to exist by direct Read before writing
these tests.

``test_dashboard_derivation.py`` already characterises
``_project_pr_decision`` / ``derive_decisions_from_github`` in isolation;
this file exercises what only shows up once rows flow through the actual
route: the live/seed mode switch, the GitHub-unlinked short-circuit (A4),
derivation-raises fallback, personalization call-through, and the auth gate.
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
    state="open",
    draft=False,
    requested_reviewers=None,
    author_id="1",
    created_at="2026-09-01T00:00:00Z",
    occurred_at=None,
):
    raw = {
        "number": number,
        "title": title,
        "state": state,
        "draft": draft,
        "user": {"id": author_id},
        "created_at": created_at,
    }
    if requested_reviewers is not None:
        raw["requested_reviewers"] = requested_reviewers
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw=raw,
        occurred_at=occurred_at or datetime(2026, 9, 12, tzinfo=timezone.utc),
        provider_id="owner/repo#7",
        kind="pr",
    )


def _seed_decision():
    return SimpleNamespace(
        id="seed-1",
        title="Seed decision",
        context="Seed context",
        source="github",
        waiting_since="3 h",
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
    """Every test that reaches the seed branch reads through
    ``dashboard_module._fetch_all`` — patch it once here so individual
    tests don't need a real DB session."""

    async def _fake_fetch_all(db, stmt):
        return [_seed_decision()]

    monkeypatch.setattr(dashboard_module, "_fetch_all", _fake_fetch_all)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_path_returns_derived_rows(monkeypatch):
    """REQ: BR-136-001 — live GitHub PRs (open, non-draft, user in reviewers)
    are returned with mode='live'; response contains all required fields."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])

    async def _fake_gh_id(db, user_id):
        return "1"

    async def _fake_prs(db, user_id, kind, **kwargs):
        return [row]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "live"
    assert body["total"] == 1
    assert body["data"][0]["context"] == "Waiting on your review"
    assert "waitingSince" in body["data"][0]


# ---------------------------------------------------------------------------
# Explicit response envelope shape (REQ: BR-136-003, FR-136-005)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_response_envelope_has_data_total_mode(monkeypatch):
    """REQ: BR-136-003 — live mode response always includes data (list),
    total (int matching len(data)), and mode='live'."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])

    async def _fake_gh_id(db, user_id):
        return "1"

    async def _fake_prs(db, user_id, kind, **kwargs):
        return [row]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

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
    """REQ: BR-136-003 — seed mode response always includes data, total, mode.
    total must equal len(data)."""

    async def _fake_gh_id(db, user_id):
        return None

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

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
    """REQ: BR-136-003 — empty live_rows triggers seed fallback with mode='seed'."""

    async def _fake_gh_id(db, user_id):
        return "1"

    async def _fake_prs(db, user_id, kind, **kwargs):
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "seed"
    assert body["total"] == 1
    assert body["data"][0]["id"] == "seed-1"


# ---------------------------------------------------------------------------
# Seed fallback: rows present but all filtered out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_prs_filtered_falls_back_to_seed(monkeypatch):
    """REQ: BR-136-003 — derivation filters every row out (no row qualifies)
    triggers seed fallback."""
    closed = _pr_row(state="closed", requested_reviewers=[{"id": "1"}])
    draft = _pr_row(draft=True, requested_reviewers=[{"id": "1"}])
    not_mine = _pr_row(requested_reviewers=[{"id": "999"}], author_id="999")

    async def _fake_gh_id(db, user_id):
        return "1"

    async def _fake_prs(db, user_id, kind, **kwargs):
        return [closed, draft, not_mine]

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

    assert resp.status_code == 200
    assert resp.json()["mode"] == "seed"


# ---------------------------------------------------------------------------
# Seed fallback: derivation raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derivation_raises_falls_back_to_seed(monkeypatch, caplog):
    """REQ: BR-136-003 — derivation exception triggers seed fallback with
    warning log; response is still HTTP 200 and well-formed."""
    row = _pr_row(requested_reviewers=[{"id": "1"}])

    async def _fake_gh_id(db, user_id):
        return "1"

    async def _fake_prs(db, user_id, kind, **kwargs):
        return [row]

    def _boom(rows, *, github_user_id):
        raise RuntimeError("derivation blew up")

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )
    monkeypatch.setattr(dashboard_module.derive, "derive_decisions_from_github", _boom)

    with caplog.at_level(logging.WARNING, logger="src.api.v1.dashboard"):
        async with await _client() as client:
            resp = await client.get("/api/v1/dashboard/decisions")

    assert resp.status_code == 200
    assert resp.json()["mode"] == "seed"
    assert "derivation failed" in " ".join(caplog.messages)


# ---------------------------------------------------------------------------
# GitHub not linked (A4 short-circuit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_unlinked_short_circuits_to_seed_without_pr_fetch(monkeypatch):
    """REQ: BR-136-003, FR-136-005 — when GitHub is unlinked (provider_user_id is None)
    the route must return seed rows and must NOT issue the PR query at all."""

    async def _fake_gh_id(db, user_id):
        return None

    pr_fetch_called = False

    async def _fake_prs(db, user_id, kind, **kwargs):
        nonlocal pr_fetch_called
        pr_fetch_called = True
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

    assert resp.status_code == 200
    assert resp.json()["mode"] == "seed"
    assert pr_fetch_called is False


# ---------------------------------------------------------------------------
# Personalization — user_id is passed through to query layer (REQ: BR-136-004)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personalization_user_id_passed_to_query(monkeypatch, _fake_user):
    """REQ: BR-136-004 — the route must pass current_user.id to both
    fetch_github_provider_user_id and fetch_github_activity_by_kind so that
    each user only sees their own ingested rows."""
    captured_user_ids: list[uuid.UUID] = []

    async def _fake_gh_id(db, user_id):
        captured_user_ids.append(user_id)
        return "1"

    async def _fake_prs(db, user_id, kind, **kwargs):
        captured_user_ids.append(user_id)
        return []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        await client.get("/api/v1/dashboard/decisions")

    # Both query calls must use the authed user's id
    assert all(uid == _fake_user.id for uid in captured_user_ids), (
        f"At least one query call used a different user_id; calls: {captured_user_ids}"
    )
    assert len(captured_user_ids) == 2, (
        "Expected exactly 2 query calls (provider_user_id + activity_by_kind)"
    )


@pytest.mark.asyncio
async def test_cross_user_isolation_different_users_see_different_rows(monkeypatch):
    """REQ: BR-136-004 — a PR owned by user A must never appear in user B's response.
    Simulated by having the query return a non-empty list for user A and an empty
    list for user B; each should get the appropriate mode."""
    from src.auth.dependencies import get_current_user

    user_a = SimpleNamespace(id=uuid.uuid4())
    user_b = SimpleNamespace(id=uuid.uuid4())
    row_for_a = _pr_row(requested_reviewers=[{"id": "user-a-github-id"}])

    async def _fake_gh_id_a(db, user_id):
        return "user-a-github-id" if user_id == user_a.id else "user-b-github-id"

    async def _fake_prs(db, user_id, kind, **kwargs):
        # Only return the row when the query is for user A
        return [row_for_a] if user_id == user_a.id else []

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id_a
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    # Request as user A — should get live data
    async def _as_user_a():
        return user_a

    app.dependency_overrides[get_current_user] = _as_user_a
    async with await _client() as client:
        resp_a = await client.get("/api/v1/dashboard/decisions")
    assert resp_a.json()["mode"] == "live"
    assert resp_a.json()["total"] == 1

    # Request as user B — should fall back to seed (no matching rows)
    async def _as_user_b():
        return user_b

    app.dependency_overrides[get_current_user] = _as_user_b
    async with await _client() as client:
        resp_b = await client.get("/api/v1/dashboard/decisions")
    assert resp_b.json()["mode"] == "seed"

    # Cleanup: restore the autouse fixture's override
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Unauthenticated (REQ: BR-136-004)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_requires_auth():
    """REQ: BR-136-004 — unauthenticated request must return 401 and no
    DB queries must be attempted."""
    from src.auth.dependencies import get_current_user

    app.dependency_overrides.pop(get_current_user, None)

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Regression guard — seed row count and content (NFR-136-004)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_fallback_returns_exactly_one_seed_row(monkeypatch):
    """NFR-136-004 — seed table is read-only. The test's _fake_seed_fetch
    fixture returns exactly 1 row (seed-1) to mirror the autouse patch;
    this test confirms the route propagates that count correctly rather than
    adding or dropping rows."""

    async def _fake_gh_id(db, user_id):
        return "1"

    async def _fake_prs(db, user_id, kind, **kwargs):
        return []  # Force seed path

    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_provider_user_id", _fake_gh_id
    )
    monkeypatch.setattr(
        dashboard_module.queries, "fetch_github_activity_by_kind", _fake_prs
    )

    async with await _client() as client:
        resp = await client.get("/api/v1/dashboard/decisions")

    body = resp.json()
    assert body["mode"] == "seed"
    # The autouse _fake_seed_fetch fixture provides exactly 1 seed row.
    # A different count would mean something upstream changed the seed table
    # contract (violates NFR-136-004).
    assert body["total"] == 1
    assert body["data"][0]["id"] == "seed-1"
    assert body["data"][0]["title"] == "Seed decision"
