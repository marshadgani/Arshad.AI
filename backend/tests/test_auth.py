"""Tests for /api/v1/auth/* routes."""

import hashlib as _hashlib
import hmac as _hmac
import os
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from src.auth.routers import _make_signed_state, _verify_signed_state
from src.main import app

client = TestClient(app)


@pytest.fixture
def mock_db():
    """Override get_db with a no-op so DB-dependent routes work in unit tests."""
    from src.models.database import get_db

    async def _override():
        yield MagicMock()

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()


# ── Unit tests: _make_signed_state / _verify_signed_state ─────────────────────


def test_make_signed_state_roundtrips():
    signed = _make_signed_state("abc123")
    assert _verify_signed_state(signed)


def test_verify_signed_state_rejects_tampered_sig():
    signed = _make_signed_state("abc123")
    tampered = signed[:-4] + "0000"
    assert not _verify_signed_state(tampered)


def test_verify_signed_state_rejects_tampered_nonce():
    signed = _make_signed_state("abc123")
    parts = signed.split(".")
    parts[0] = "evil"
    assert not _verify_signed_state(".".join(parts))


def test_verify_signed_state_rejects_expired(monkeypatch):
    signed = _make_signed_state("abc123")
    future = time.time() + 400
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod.time, "time", lambda: future)
    assert not _verify_signed_state(signed)


def test_verify_signed_state_rejects_malformed():
    assert not _verify_signed_state("notvalid")
    assert not _verify_signed_state("")
    assert not _verify_signed_state("only.two")


def test_verify_signed_state_rejects_non_numeric_timestamp():
    signed = _make_signed_state("abc123")
    parts = signed.split(".", 2)
    parts[1] = "not-a-number"
    assert not _verify_signed_state(".".join(parts))


def test_verify_signed_state_rejects_empty_nonce():
    signed = _make_signed_state("abc123")
    parts = signed.split(".", 2)
    parts[0] = ""
    assert not _verify_signed_state(".".join(parts))


def test_verify_signed_state_rejects_future_timestamp():
    """A cryptographically valid signed state with a future timestamp is rejected (clock skew)."""
    nonce = "testnonce"
    ts_str = str(int(time.time()) + 3600)
    payload = f"{nonce}.{ts_str}"
    key = os.getenv("SECRET_KEY", "").encode()
    sig = _hmac.new(key, payload.encode(), _hashlib.sha256).hexdigest()
    assert not _verify_signed_state(f"{nonce}.{ts_str}.{sig}")


# ── Integration tests: login redirect ─────────────────────────────────────────


def test_google_login_redirects_to_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-google-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")
    with TestClient(app, follow_redirects=False) as tc:
        response = tc.get("/api/v1/auth/google/login")
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]
    assert "test-google-id" in response.headers["location"]


def test_github_login_redirects_to_github(monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "test-github-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "test-github-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")
    with TestClient(app, follow_redirects=False) as tc:
        response = tc.get("/api/v1/auth/github/login")
    assert response.status_code == 302
    assert "github.com" in response.headers["location"]
    assert "test-github-id" in response.headers["location"]


# ── Integration tests: callback state validation at HTTP level ─────────────────


def test_google_callback_rejects_invalid_state(mock_db):
    response = client.get(
        "/api/v1/auth/google/callback?code=fakecode&state=bad.state.value"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_state"


def test_github_callback_rejects_invalid_state(mock_db):
    response = client.get(
        "/api/v1/auth/github/callback?code=fakecode&state=bad.state.value"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_state"


def test_google_callback_rejects_expired_state(mock_db, monkeypatch):
    signed = _make_signed_state("abc123")
    future = time.time() + 400
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod.time, "time", lambda: future)
    response = client.get(f"/api/v1/auth/google/callback?code=fakecode&state={signed}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_state"


# ── Integration tests: /me endpoint ───────────────────────────────────────────


def test_me_without_auth_returns_401(mock_db):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_authorization"


def test_me_with_valid_user_returns_data(mock_db):
    """Override get_current_user to skip JWT/DB and verify the /me response shape."""
    import uuid
    from unittest.mock import MagicMock

    from src.auth.dependencies import get_current_user

    mock_user = MagicMock()
    mock_user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    mock_user.email = "arshad@example.com"
    mock_user.name = "Arshad"
    mock_user.avatar_url = None

    async def override_auth():
        return mock_user

    app.dependency_overrides[get_current_user] = override_auth
    try:
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer fake-token"}
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["email"] == "arshad@example.com"
    assert data["name"] == "Arshad"
    assert data["avatarUrl"] is None


# ── Integration tests: logout ──────────────────────────────────────────────────


def test_logout_returns_204():
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert response.content == b""
