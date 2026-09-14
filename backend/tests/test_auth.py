"""Tests for /api/v1/auth/* routes."""

import hashlib as _hashlib
import hmac as _hmac
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.auth.routers import (
    _handle_callback,
    _login_nonce_key,
    _make_signed_state,
    _verify_signed_state,
)
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
    key = b"test-secret-key-for-unit-tests"
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


# ── Unit tests: SEC-002 login-CSRF / session-fixation fix ─────────────────────
# _handle_callback's nonce-cookie binding and single-use Redis check, tested
# directly (not via HTTP) so they don't need a live Postgres/Redis — these
# cover exactly the rejection paths that close the finding: a stolen/replayed
# state with no matching cookie, or reused after its Redis entry is consumed.


@pytest.mark.asyncio
async def test_handle_callback_rejects_missing_cookie_nonce():
    """An attacker-supplied state with no corresponding browser cookie is rejected
    before any Redis lookup or provider call — this is the core CSRF fix."""
    signed = _make_signed_state("victim-nonce")
    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, None, MagicMock())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["code"] == "invalid_state"


@pytest.mark.asyncio
async def test_handle_callback_rejects_mismatched_cookie_nonce():
    """A state signed for one nonce presented with a different browser cookie
    (e.g. the attacker's own prior login flow) is rejected."""
    signed = _make_signed_state("real-nonce")
    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, "different-nonce", MagicMock())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["code"] == "invalid_state"


@pytest.mark.asyncio
async def test_handle_callback_rejects_already_consumed_state(monkeypatch):
    """A matching cookie+state pair is still rejected if the Redis entry was
    already GETDEL'd by a prior callback — kills replay of a valid state."""
    nonce = "one-shot-nonce"
    signed = _make_signed_state(nonce)

    mock_redis = MagicMock()
    mock_redis.getdel = AsyncMock(return_value=None)  # already consumed / expired

    async def _fake_get_redis():
        return mock_redis

    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, nonce, MagicMock())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["code"] == "invalid_state"
    mock_redis.getdel.assert_awaited_once_with(_login_nonce_key(nonce))


# ── Unit tests: FEAT-158 login allowlist (AUTH_ALLOWED_EMAILS) ────────────────
# _handle_callback tested directly with a mocked provider + Redis, same
# no-live-DB approach as the SEC-002 tests above, so the gate can be proven
# to reject BEFORE upsert_user_from_oauth ever creates a User row.


def _fake_redis_consumable():
    mock_redis = MagicMock()
    mock_redis.getdel = AsyncMock(return_value="1")

    async def _fake_get_redis():
        return mock_redis

    return _fake_get_redis


def _fake_provider(email: str):
    provider = MagicMock()
    provider.exchange_code = AsyncMock(
        return_value=MagicMock(access_token="tok", refresh_token=None)
    )
    provider.fetch_user_info = AsyncMock(
        return_value=MagicMock(
            email=email,
            provider_user_id="provider-user-1",
            name="Test User",
            avatar_url=None,
        )
    )
    return provider


@pytest.mark.asyncio
async def test_handle_callback_rejects_email_not_on_allowlist(monkeypatch):
    """An OAuth-verified email outside AUTH_ALLOWED_EMAILS is rejected with
    403 before any User row is created — closes the open-signup gap that let
    any Google/GitHub account reach shared project integrations."""
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "get_redis", _fake_redis_consumable())
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setattr(
        routers_mod, "_provider", lambda name: _fake_provider("attacker@example.com")
    )
    upsert_mock = AsyncMock()
    monkeypatch.setattr(routers_mod, "upsert_user_from_oauth", upsert_mock)

    nonce = "gate-nonce-1"
    signed = _make_signed_state(nonce)
    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, nonce, MagicMock())
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"]["code"] == "email_not_allowed"
    upsert_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_callback_allows_email_on_allowlist_case_insensitive(monkeypatch):
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "get_redis", _fake_redis_consumable())
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "Owner@Example.com")
    monkeypatch.setattr(
        routers_mod, "_provider", lambda name: _fake_provider("owner@example.com")
    )
    fake_user = MagicMock(id="user-1")
    upsert_mock = AsyncMock(return_value=fake_user)
    monkeypatch.setattr(routers_mod, "upsert_user_from_oauth", upsert_mock)

    nonce = "gate-nonce-2"
    signed = _make_signed_state(nonce)
    response = await _handle_callback("google", "code", signed, nonce, MagicMock())
    assert response.status_code == 302
    upsert_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_callback_denies_everyone_when_allowlist_unset_and_no_opt_in(
    monkeypatch,
):
    """Deny-by-default: empty AUTH_ALLOWED_EMAILS with no explicit
    AUTH_ALLOW_ALL_LOGINS opt-in denies login, not permits it."""
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "get_redis", _fake_redis_consumable())
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("AUTH_ALLOW_ALL_LOGINS", raising=False)
    monkeypatch.setattr(
        routers_mod, "_provider", lambda name: _fake_provider("anyone@example.com")
    )
    upsert_mock = AsyncMock()
    monkeypatch.setattr(routers_mod, "upsert_user_from_oauth", upsert_mock)

    nonce = "gate-nonce-3"
    signed = _make_signed_state(nonce)
    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, nonce, MagicMock())
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"]["code"] == "email_not_allowed"
    upsert_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_callback_allows_everyone_with_local_dev_opt_in(monkeypatch):
    """AUTH_ALLOW_ALL_LOGINS=true is the explicit local-dev escape hatch."""
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "get_redis", _fake_redis_consumable())
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    monkeypatch.setattr(
        routers_mod, "_provider", lambda name: _fake_provider("anyone@example.com")
    )
    fake_user = MagicMock(id="user-1")
    upsert_mock = AsyncMock(return_value=fake_user)
    monkeypatch.setattr(routers_mod, "upsert_user_from_oauth", upsert_mock)

    nonce = "gate-nonce-3"
    signed = _make_signed_state(nonce)
    response = await _handle_callback("google", "code", signed, nonce, MagicMock())
    assert response.status_code == 302
    upsert_mock.assert_awaited_once()


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
