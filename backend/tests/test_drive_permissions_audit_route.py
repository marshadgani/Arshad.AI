"""Route-level tests for GET /api/v1/drive/permissions-audit.

FN-101, FN-102, FN-104, NF-204, NF-205, NF-206, NF-208.
Always-200 contract matrix and query-param validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.services.drive import DriveAuditResult, DriveAuditService, FileAuditResult

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
USER_A = SimpleNamespace(id=uuid.uuid4(), email="a@example.com")
USER_B = SimpleNamespace(id=uuid.uuid4(), email="b@example.com")


def _ok_result(**kw):
    defaults = dict(
        files=[],
        total=0,
        connected=True,
        needs_reauth=False,
        truncated=False,
        partial_failures=[],
    )
    defaults.update(kw)
    return DriveAuditResult(**defaults)


def _not_connected():
    return DriveAuditResult()


def _needs_reauth():
    return DriveAuditResult(
        connected=True,
        needs_reauth=True,
        partial_failures=["google_drive: needs_reauth"],
    )


def _partial_failure(label):
    return DriveAuditResult(connected=True, partial_failures=[f"google_drive: {label}"])


@pytest.fixture
def client(monkeypatch):
    """TestClient with auth and DB overrides."""
    app.dependency_overrides[get_current_user] = lambda: USER_A

    async def _fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = _fake_db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _mock_service(monkeypatch, result: DriveAuditResult):
    async def _audit(user_id, db, *, limit, stale_days, now):
        return result

    monkeypatch.setattr(DriveAuditService, "get_audit_results", staticmethod(_audit))


# ---------------------------------------------------------------------------
# FN-104 — always-200 matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario,result_fn",
    [
        ("not_connected", _not_connected),
        ("needs_reauth", _needs_reauth),
        ("rate_limited", lambda: _partial_failure("rate_limited")),
        ("fetch_failed", lambda: _partial_failure("fetch_failed")),
        ("network_error", lambda: _partial_failure("network_error")),
        ("forbidden", lambda: _partial_failure("forbidden")),
    ],
)
class TestAlways200:
    def test_returns_200(self, monkeypatch, client, scenario, result_fn):
        _mock_service(monkeypatch, result_fn())
        resp = client.get("/api/v1/drive/permissions-audit")
        assert resp.status_code == 200

    def test_body_has_six_keys(self, monkeypatch, client, scenario, result_fn):
        _mock_service(monkeypatch, result_fn())
        body = client.get("/api/v1/drive/permissions-audit").json()
        for key in (
            "data",
            "total",
            "connected",
            "needs_reauth",
            "truncated",
            "partial_failures",
        ):
            assert key in body


# ---------------------------------------------------------------------------
# Not connected / needs_reauth
# ---------------------------------------------------------------------------


class TestNotConnected:
    def test_not_connected_body(self, monkeypatch, client):
        _mock_service(monkeypatch, _not_connected())
        body = client.get("/api/v1/drive/permissions-audit").json()
        assert body["connected"] is False
        assert body["needs_reauth"] is False
        assert body["data"] == []

    def test_needs_reauth_never_returns_401_or_403(self, monkeypatch, client):
        _mock_service(monkeypatch, _needs_reauth())
        resp = client.get("/api/v1/drive/permissions-audit")
        assert resp.status_code == 200
        assert resp.json()["needs_reauth"] is True


# ---------------------------------------------------------------------------
# FN-101 — DriveFile response shape
# ---------------------------------------------------------------------------


class TestFileShape:
    def test_drive_file_shape(self, monkeypatch, client):
        file_result = FileAuditResult(
            id="f1",
            name="doc.pdf",
            web_view_link="https://drive.google.com/f1",
            modified_time="2025-01-01T00:00:00Z",
            anyone_with_link=True,
            stale_sharing=False,
            permissions_visible=True,
        )
        _mock_service(monkeypatch, _ok_result(files=[file_result], total=1))
        body = client.get("/api/v1/drive/permissions-audit").json()
        f = body["data"][0]
        for key in (
            "id",
            "name",
            "web_view_link",
            "modified_time",
            "anyone_with_link",
            "stale_sharing",
            "permissions_visible",
        ):
            assert key in f

    def test_response_contains_no_token_or_email(self, monkeypatch, client):
        _mock_service(monkeypatch, _ok_result())
        text = client.get("/api/v1/drive/permissions-audit").text
        assert "fake-token" not in text
        assert "@example.com" not in text


# ---------------------------------------------------------------------------
# FN-101 — query param validation (NF-204)
# ---------------------------------------------------------------------------


class TestQueryValidation:
    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"limit": -1},
            {"stale_days": 0},
            {"stale_days": 3651},
            {"stale_days": "abc"},
        ],
    )
    def test_invalid_params_return_422(self, monkeypatch, client, params):
        _mock_service(monkeypatch, _ok_result())
        resp = client.get("/api/v1/drive/permissions-audit", params=params)
        assert resp.status_code == 422

    def test_boundary_limit_1_accepted(self, monkeypatch, client):
        _mock_service(monkeypatch, _ok_result())
        assert (
            client.get(
                "/api/v1/drive/permissions-audit", params={"limit": 1}
            ).status_code
            == 200
        )

    def test_boundary_limit_100_accepted(self, monkeypatch, client):
        _mock_service(monkeypatch, _ok_result())
        assert (
            client.get(
                "/api/v1/drive/permissions-audit", params={"limit": 100}
            ).status_code
            == 200
        )

    def test_boundary_stale_days_1_accepted(self, monkeypatch, client):
        _mock_service(monkeypatch, _ok_result())
        assert (
            client.get(
                "/api/v1/drive/permissions-audit", params={"stale_days": 1}
            ).status_code
            == 200
        )

    def test_boundary_stale_days_3650_accepted(self, monkeypatch, client):
        _mock_service(monkeypatch, _ok_result())
        assert (
            client.get(
                "/api/v1/drive/permissions-audit", params={"stale_days": 3650}
            ).status_code
            == 200
        )

    def test_default_params_reach_service(self, monkeypatch, client):
        received = {}

        async def _capture(user_id, db, *, limit, stale_days, now):
            received["limit"] = limit
            received["stale_days"] = stale_days
            return _ok_result()

        monkeypatch.setattr(
            DriveAuditService, "get_audit_results", staticmethod(_capture)
        )
        client.get("/api/v1/drive/permissions-audit")
        assert received["limit"] == 20
        assert received["stale_days"] == 180


# ---------------------------------------------------------------------------
# NF-208 — per-user scoping
# ---------------------------------------------------------------------------


class TestUserScoping:
    def test_user_id_forwarded_to_service(self, monkeypatch, client):
        received = {}

        async def _capture(user_id, db, *, limit, stale_days, now):
            received["user_id"] = user_id
            return _ok_result()

        monkeypatch.setattr(
            DriveAuditService, "get_audit_results", staticmethod(_capture)
        )
        client.get("/api/v1/drive/permissions-audit")
        assert received["user_id"] == USER_A.id

    def test_unauthenticated_returns_401(self):
        """Auth dependency raises 401 for missing/invalid token."""
        client_no_auth = TestClient(app, raise_server_exceptions=False)
        resp = client_no_auth.get("/api/v1/drive/permissions-audit")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Truncated flag
# ---------------------------------------------------------------------------


class TestTruncated:
    def test_truncated_true_in_response(self, monkeypatch, client):
        _mock_service(monkeypatch, _ok_result(truncated=True))
        body = client.get("/api/v1/drive/permissions-audit").json()
        assert body["truncated"] is True


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    def test_route_present_in_openapi(self):
        client = TestClient(app)
        schema = client.get("/openapi.json").json()
        paths = schema.get("paths", {})
        assert "/api/v1/drive/permissions-audit" in paths

    def test_no_trailing_slash(self):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/drive/permissions-audit/")
        # Either 200 (redirect followed) or 307/404 — NOT 500
        assert resp.status_code != 500
