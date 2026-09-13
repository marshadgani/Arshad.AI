"""Tests for /api/v1/auth/* routes."""

import hashlib
import hashlib as _hashlib
import hmac as _hmac
import secrets
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.auth.routers import (
    _handle_callback,
    _is_valid_binder,
    _login_nonce_key,
    _make_signed_state,
    _start_login,
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


# ── T7 / T13: no-oracle invariant + log discrimination (flag-off path) ────────


@pytest.mark.asyncio
async def test_callback_rejection_body_identical_absent_vs_mismatch():
    """T7 — cookie_absent and cookie_mismatch must produce byte-identical HTTP
    bodies so the log-only discrimination in T13 can never leak into the
    client-visible response (no error oracle)."""
    signed = _make_signed_state("real-nonce")

    with pytest.raises(Exception) as absent_exc:
        await _handle_callback("google", "code", signed, None, MagicMock())
    with pytest.raises(Exception) as mismatch_exc:
        await _handle_callback("google", "code", signed, "different-nonce", MagicMock())

    assert absent_exc.value.status_code == mismatch_exc.value.status_code == 400
    assert absent_exc.value.detail == mismatch_exc.value.detail


@pytest.mark.asyncio
async def test_callback_rejection_logs_discriminate_reason(caplog):
    """T13 — the WARN log line (not the HTTP body) is where cookie_absent vs
    cookie_mismatch actually get told apart, per the FEAT-142 W1 diagnostic."""
    signed = _make_signed_state("real-nonce")

    with caplog.at_level("WARNING"):
        with pytest.raises(Exception):
            await _handle_callback("google", "code", signed, None, MagicMock())
    assert "reason=cookie_absent" in caplog.text
    assert "cookie_present=False" in caplog.text

    caplog.clear()
    with caplog.at_level("WARNING"):
        with pytest.raises(Exception):
            await _handle_callback(
                "google", "code", signed, "different-nonce", MagicMock()
            )
    assert "reason=cookie_mismatch" in caplog.text
    assert "cookie_present=True" in caplog.text


# ── T10 / T11: Redis outage fails closed, never open ───────────────────────────


@pytest.mark.asyncio
async def test_start_login_fails_closed_when_redis_set_raises(monkeypatch):
    """T10 — a Redis outage during _start_login must surface as 503
    login_unavailable, never as a login that silently skips the CSRF state."""
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(side_effect=ConnectionError("redis down"))

    async def _fake_get_redis():
        return mock_redis

    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-google-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")

    with pytest.raises(Exception) as exc_info:
        await _start_login("google")
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"]["code"] == "login_unavailable"


@pytest.mark.asyncio
async def test_handle_callback_fails_closed_when_redis_getdel_raises(monkeypatch):
    """T11 — same fail-closed contract on the callback's GETDEL call."""
    nonce = "some-nonce"
    signed = _make_signed_state(nonce)

    mock_redis = MagicMock()
    mock_redis.getdel = AsyncMock(side_effect=ConnectionError("redis down"))

    async def _fake_get_redis():
        return mock_redis

    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, nonce, MagicMock())
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"]["code"] == "login_unavailable"


# ── T14: binder length is derived, not hard-coded ───────────────────────────────


def test_binder_length_matches_token_urlsafe_round_trip():
    """T14 — _is_valid_binder's length check is computed from the same
    secrets.token_urlsafe call it validates, so a byte-size change can't
    silently make every real cookie 'malformed'."""
    import secrets as _secrets

    import src.auth.routers as routers_mod

    sample = _secrets.token_urlsafe(routers_mod._BINDER_BYTES)
    assert _is_valid_binder(sample)
    assert not _is_valid_binder(sample + "x")
    assert not _is_valid_binder(sample[:-1])


# ── W2 binder-model tests (T1-T6, T12) — run with the flag forced on ──────────
# The flag-OFF tests above (and the pre-existing SEC-002 tests) are the
# shipping-path coverage and are left unmodified per the system design.


@pytest.fixture
def binder_enabled(monkeypatch):
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod, "OAUTH_STATE_BINDER_ENABLED", True)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-google-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")
    yield


class _FakeRedisStore:
    """In-memory stand-in for the Redis calls _start_login/_handle_callback
    make, so the binder tests exercise the real set/getdel semantics."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def getdel(self, key):
        return self._store.pop(key, None)


@pytest.mark.asyncio
async def test_binder_reused_across_sequential_start_login_calls(
    binder_enabled, monkeypatch
):
    """T1 — a second _start_login carrying the first's cookie reuses the same
    binder; both resulting states verify against the same Redis commitment."""
    import src.auth.routers as routers_mod

    fake_redis = _FakeRedisStore()

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    first = await _start_login("google", None)
    first_binder = (
        first.headers["set-cookie"].split("oauth_browser_binder=")[1].split(";")[0]
    )

    second = await _start_login("google", first_binder)
    second_binder = (
        second.headers["set-cookie"].split("oauth_browser_binder=")[1].split(";")[0]
    )

    assert first_binder == second_binder


@pytest.mark.asyncio
async def test_binder_minted_fresh_when_cookie_absent(binder_enabled, monkeypatch):
    """T2 — with no incoming cookie, _start_login mints a fresh valid binder."""
    import src.auth.routers as routers_mod

    fake_redis = _FakeRedisStore()

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    response = await _start_login("google", None)
    binder = (
        response.headers["set-cookie"].split("oauth_browser_binder=")[1].split(";")[0]
    )
    assert _is_valid_binder(binder)


@pytest.mark.asyncio
async def test_binder_callback_rejects_absent_cookie(binder_enabled, monkeypatch):
    """T3 — cookie absent at callback is rejected, and GETDEL still ran first
    (the Redis entry is gone even though the callback failed)."""
    import src.auth.routers as routers_mod

    nonce = "state-nonce"
    signed = _make_signed_state(nonce)
    binder = secrets.token_urlsafe(32)
    fake_redis = _FakeRedisStore()
    await fake_redis.set(
        _login_nonce_key(nonce), hashlib.sha256(binder.encode()).hexdigest()
    )

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, None, MagicMock())
    assert exc_info.value.status_code == 400
    assert fake_redis._store == {}  # GETDEL already consumed it


@pytest.mark.asyncio
async def test_binder_callback_rejects_wrong_binder(binder_enabled, monkeypatch):
    """T4 — cookie present but hashing to the wrong commitment is rejected."""
    import src.auth.routers as routers_mod

    nonce = "state-nonce"
    signed = _make_signed_state(nonce)
    correct_binder = secrets.token_urlsafe(32)
    wrong_binder = secrets.token_urlsafe(32)
    fake_redis = _FakeRedisStore()
    await fake_redis.set(
        _login_nonce_key(nonce), hashlib.sha256(correct_binder.encode()).hexdigest()
    )

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, wrong_binder, MagicMock())
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_binder_callback_replay_rejected(binder_enabled, monkeypatch):
    """T5 — a second callback with the same state after the first consumed it
    is rejected (GETDEL already returned None)."""
    import src.auth.routers as routers_mod

    nonce = "state-nonce"
    signed = _make_signed_state(nonce)
    binder = secrets.token_urlsafe(32)
    fake_redis = _FakeRedisStore()
    await fake_redis.set(
        _login_nonce_key(nonce), hashlib.sha256(binder.encode()).hexdigest()
    )

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    # Simulates a prior callback (from a first tab, or a replay) already
    # having burned the single-use Redis entry via GETDEL.
    assert await fake_redis.getdel(_login_nonce_key(nonce)) is not None

    with pytest.raises(Exception) as exc_info:
        await _handle_callback("google", "code", signed, binder, MagicMock())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["code"] == "invalid_state"


@pytest.mark.asyncio
async def test_binder_callback_rejects_bad_signature_before_redis(
    binder_enabled, monkeypatch
):
    """T6 — a bad signature is rejected before any Redis call is attempted."""
    import src.auth.routers as routers_mod

    called = False

    async def _fake_get_redis():
        nonlocal called
        called = True
        raise AssertionError("Redis must not be touched for a bad signature")

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    with pytest.raises(Exception) as exc_info:
        await _handle_callback(
            "google", "code", "bad.state.value", "some-binder", MagicMock()
        )
    assert exc_info.value.status_code == 400
    assert not called


@pytest.mark.asyncio
async def test_binder_two_tab_second_callback_still_validates(
    binder_enabled, monkeypatch
):
    """T12 — two tabs sharing one binder: the first callback's success must
    NOT invalidate the shared binder cookie for whichever tab finishes
    second. Regression test for the earlier delete-on-success defect."""
    import src.auth.routers as routers_mod

    binder = secrets.token_urlsafe(32)
    nonce_a, nonce_b = "nonce-a", "nonce-b"
    signed_a, signed_b = _make_signed_state(nonce_a), _make_signed_state(nonce_b)
    fake_redis = _FakeRedisStore()
    stored_hash = hashlib.sha256(binder.encode()).hexdigest()
    await fake_redis.set(_login_nonce_key(nonce_a), stored_hash)
    await fake_redis.set(_login_nonce_key(nonce_b), stored_hash)

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(routers_mod, "get_redis", _fake_get_redis)

    class _StubBundle:
        access_token = "tok"

    class _StubInfo:
        pass

    class _StubProvider:
        async def exchange_code(self, code):
            return _StubBundle()

        async def fetch_user_info(self, access_token):
            return _StubInfo()

    monkeypatch.setattr(routers_mod, "_provider", lambda name: _StubProvider())

    async def _fake_upsert(db, *, provider, info, bundle):
        return MagicMock(id="user-1")

    monkeypatch.setattr(routers_mod, "upsert_user_from_oauth", _fake_upsert)
    monkeypatch.setattr(routers_mod, "encode_jwt", lambda user_id: "jwt-token")

    first_response = await _handle_callback(
        "google", "code-a", signed_a, binder, MagicMock()
    )
    assert first_response.status_code == 302
    # The binder cookie must NOT be cleared by the first tab's success.
    assert "oauth_browser_binder=" not in first_response.headers.get("set-cookie", "")

    second_response = await _handle_callback(
        "google", "code-b", signed_b, binder, MagicMock()
    )
    assert second_response.status_code == 302


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
