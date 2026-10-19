"""Route tests for GET /api/v1/dashboard/knowledge-suggestions.

FN-105, FN-106, NF-208: per-user, no seed rows, additive contract.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.services.drive import DriveAuditService, KnowledgeSuggestionsResult

USER_A = SimpleNamespace(id=uuid.uuid4(), email="a@example.com")
USER_B = SimpleNamespace(id=uuid.uuid4(), email="b@example.com")


def _ok_result(**kw):
    defaults = dict(
        names=[],
        total=0,
        connected=True,
        needs_reauth=False,
        truncated=False,
        partial_failures=[],
    )
    defaults.update(kw)
    return KnowledgeSuggestionsResult(**defaults)


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: USER_A

    async def _db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = _db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _mock_suggestions(monkeypatch, result):
    async def _fn(user_id, db):
        return result

    monkeypatch.setattr(
        DriveAuditService, "get_knowledge_suggestions", staticmethod(_fn)
    )


# ---------------------------------------------------------------------------
# FN-105 — not connected returns honest empty state (no seed rows)
# ---------------------------------------------------------------------------


class TestNotConnected:
    def test_not_connected_returns_empty_data(self, monkeypatch, client):
        _mock_suggestions(monkeypatch, KnowledgeSuggestionsResult())
        body = client.get("/api/v1/dashboard/knowledge-suggestions").json()
        assert body["connected"] is False
        assert body["data"] == []
        assert body["total"] == 0

    def test_seed_rows_not_returned_when_drive_disconnected(self, monkeypatch, client):
        """Regression: seed rows from KNOWLEDGE_SUGGESTIONS must not appear."""
        _mock_suggestions(monkeypatch, KnowledgeSuggestionsResult())
        body = client.get("/api/v1/dashboard/knowledge-suggestions").json()
        assert all(isinstance(x, str) for x in body["data"])
        assert len(body["data"]) == 0


# ---------------------------------------------------------------------------
# FN-106 — additive contract (frontend compatibility)
# ---------------------------------------------------------------------------


class TestAdditiveContract:
    def test_data_is_list_of_str(self, monkeypatch, client):
        _mock_suggestions(monkeypatch, _ok_result(names=["a.pdf", "b.xlsx"], total=2))
        body = client.get("/api/v1/dashboard/knowledge-suggestions").json()
        assert isinstance(body["data"], list)
        assert all(isinstance(x, str) for x in body["data"])

    def test_total_is_top_level_int(self, monkeypatch, client):
        _mock_suggestions(monkeypatch, _ok_result(names=["a"], total=1))
        body = client.get("/api/v1/dashboard/knowledge-suggestions").json()
        assert isinstance(body["total"], int)

    def test_new_flags_are_additive(self, monkeypatch, client):
        _mock_suggestions(monkeypatch, _ok_result())
        body = client.get("/api/v1/dashboard/knowledge-suggestions").json()
        for key in ("connected", "needs_reauth", "truncated", "partial_failures"):
            assert key in body

    def test_always_200(self, monkeypatch, client):
        _mock_suggestions(monkeypatch, KnowledgeSuggestionsResult())
        assert client.get("/api/v1/dashboard/knowledge-suggestions").status_code == 200


# ---------------------------------------------------------------------------
# NF-208 — per-user scoping
# ---------------------------------------------------------------------------


class TestUserScoping:
    def test_user_id_forwarded_to_service(self, monkeypatch, client):
        received = {}

        async def _capture(user_id, db):
            received["user_id"] = user_id
            return _ok_result()

        monkeypatch.setattr(
            DriveAuditService, "get_knowledge_suggestions", staticmethod(_capture)
        )
        client.get("/api/v1/dashboard/knowledge-suggestions")
        assert received["user_id"] == USER_A.id

    def test_requires_auth(self):
        client_no_auth = TestClient(app, raise_server_exceptions=False)
        resp = client_no_auth.get("/api/v1/dashboard/knowledge-suggestions")
        assert resp.status_code == 401

    def test_user_a_and_user_b_see_different_results(self, monkeypatch):
        """NF-208: same endpoint, different callers get different data."""

        async def _service(user_id, db):
            if user_id == USER_A.id:
                return _ok_result(names=["userA-file.pdf"], total=1)
            return _ok_result(names=["userB-file.pdf"], total=1)

        monkeypatch.setattr(
            DriveAuditService, "get_knowledge_suggestions", staticmethod(_service)
        )

        async def _db():
            yield SimpleNamespace()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: USER_A
        client_a = TestClient(app, raise_server_exceptions=False)
        body_a = client_a.get("/api/v1/dashboard/knowledge-suggestions").json()

        app.dependency_overrides[get_current_user] = lambda: USER_B
        client_b = TestClient(app, raise_server_exceptions=False)
        body_b = client_b.get("/api/v1/dashboard/knowledge-suggestions").json()

        app.dependency_overrides.clear()
        assert body_a["data"] != body_b["data"]


# ---------------------------------------------------------------------------
# needs_reauth scenario
# ---------------------------------------------------------------------------


class TestNeedsReauth:
    def test_needs_reauth_returns_200_with_flag(self, monkeypatch, client):
        _mock_suggestions(
            monkeypatch,
            KnowledgeSuggestionsResult(
                connected=True,
                needs_reauth=True,
                partial_failures=["google_drive: needs_reauth"],
            ),
        )
        resp = client.get("/api/v1/dashboard/knowledge-suggestions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["needs_reauth"] is True
        assert body["data"] == []


# ---------------------------------------------------------------------------
# No outbound HTTP during request
# ---------------------------------------------------------------------------


class TestNoOutboundHttp:
    def test_no_http_call_in_handler(self, monkeypatch, client):
        """knowledge-suggestions reads only the cache; no live Drive call."""
        called = []

        async def _list(*a, **kw):
            called.append(1)

        import src.services.drive.service as mod

        monkeypatch.setattr(mod, "list_recent_files", _list)
        _mock_suggestions(monkeypatch, _ok_result())
        client.get("/api/v1/dashboard/knowledge-suggestions")
        assert called == []
