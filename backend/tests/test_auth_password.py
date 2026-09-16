"""Tests for POST /api/v1/auth/password/login (FEAT-143) and the OAuth
Redis-resilience guards it depends on.

No wall-clock or elapsed-ms assertions anywhere in this file — the
timing-oracle invariant ("exactly one bcrypt op per request, on every
branch") is asserted with a deterministic call-count spy on
``src.auth.password._checkpw``, the single private primitive both
``verify_password`` and ``dummy_verify`` funnel through. Two independent
spy targets would make the invariant unfalsifiable (a handler calling
both on one branch would still satisfy "each <= 1" while violating
"exactly one"), which is why there is exactly one spy target in this
file.

NOTE ON T13 (OAuth regression contract): this file does not duplicate
tests/test_auth.py. The contract is that the ENTIRE pre-existing OAuth
suite in test_auth.py passes UNMODIFIED — enforced by not editing that
file, not by a runtime assertion here.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.exceptions
import src.auth.lockout as lockout_mod
import src.auth.password as password_mod
import src.auth.routers as routers_mod
import src.middleware.rate_limit as rate_limit_mod
from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.auth.providers import GoogleOAuthProvider
from src.auth.service import normalize_email
from src.main import app
from src.models.database import get_db

client = TestClient(app)
LOGIN_URL = "/api/v1/auth/password/login"


class _FakeUser:
    def __init__(self, email: str, password_hash: str | None):
        self.id = uuid.uuid4()
        self.email = email
        self.password_hash = password_hash


def _override_db(user):
    session = MagicMock()
    session.scalar = AsyncMock(return_value=user)

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    return session


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def no_backstop(monkeypatch):
    """Bypass the global rate-limit backstop so tests focus on the
    credential-check path. Does not touch the fail-CLOSED lockout — that
    stays real unless a test also patches it."""
    monkeypatch.setattr(routers_mod, "enforce_rate_limit", AsyncMock(return_value=None))


@pytest.fixture
def no_lockout(monkeypatch):
    monkeypatch.setattr(lockout_mod, "assert_not_locked", AsyncMock(return_value=None))
    monkeypatch.setattr(lockout_mod, "record_failure", AsyncMock(return_value=None))
    monkeypatch.setattr(lockout_mod, "clear_failures", AsyncMock(return_value=None))


# ── T1 / T2 — exactly one bcrypt op, identical bodies, on every branch ─────


@pytest.mark.parametrize(
    "user_factory,expect_status",
    [
        (lambda: None, 401),  # (a) user not found
        (lambda: _FakeUser("a@example.com", None), 401),  # (b) OAuth-only account
        (lambda: _FakeUser("a@example.com", "somehash"), 401),  # (c) wrong password
    ],
)
def test_exactly_one_bcrypt_op_and_generic_body_on_failure_branches(
    monkeypatch, no_backstop, no_lockout, user_factory, expect_status
):
    spy = AsyncMock(return_value=False)
    monkeypatch.setattr(password_mod, "_checkpw", spy)
    _override_db(user_factory())

    response = client.post(
        LOGIN_URL, json={"email": "a@example.com", "password": "wrong"}
    )

    assert response.status_code == expect_status
    assert spy.call_count == 1
    body = response.json()
    assert body["error"]["code"] == "invalid_credentials"
    assert body["error"]["message"] == "Email or password is incorrect."


def test_identical_401_bodies_across_failure_branches(
    monkeypatch, no_backstop, no_lockout
):
    spy = AsyncMock(return_value=False)
    monkeypatch.setattr(password_mod, "_checkpw", spy)

    bodies = []
    for user in (
        None,
        _FakeUser("a@example.com", None),
        _FakeUser("a@example.com", "h"),
    ):
        _override_db(user)
        response = client.post(
            LOGIN_URL, json={"email": "a@example.com", "password": "x"}
        )
        bodies.append((response.status_code, response.json()))

    assert all(b == bodies[0] for b in bodies), (
        "All three failure branches must return byte-identical bodies"
    )


def test_exactly_one_bcrypt_op_on_success_branch(monkeypatch, no_backstop, no_lockout):
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    spy = AsyncMock(return_value=True)
    monkeypatch.setattr(password_mod, "_checkpw", spy)
    _override_db(_FakeUser("a@example.com", "somehash"))

    response = client.post(
        LOGIN_URL, json={"email": "a@example.com", "password": "correct"}
    )

    assert response.status_code == 200
    assert "token" in response.json()["data"]
    assert spy.call_count == 1


# ── T3 / T4 — kill-switch ───────────────────────────────────────────────────


def test_kill_switch_off_returns_503(monkeypatch, no_backstop, no_lockout):
    monkeypatch.setenv("PASSWORD_AUTH_ENABLED", "false")
    response = client.post(LOGIN_URL, json={"email": "a@example.com", "password": "x"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "password_auth_disabled"


def test_kill_switch_unset_defaults_enabled(monkeypatch, no_backstop, no_lockout):
    monkeypatch.delenv("PASSWORD_AUTH_ENABLED", raising=False)
    _override_db(None)
    response = client.post(LOGIN_URL, json={"email": "a@example.com", "password": "x"})
    # Reaches the credential check (401), not the kill-switch (503) —
    # covers the "forgotten Render env var" scenario explicitly.
    assert response.status_code == 401


def test_kill_switch_off_does_not_affect_oauth(monkeypatch):
    monkeypatch.setenv("PASSWORD_AUTH_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")
    with TestClient(app, follow_redirects=False) as tc:
        response = tc.get("/api/v1/auth/google/login")
    assert response.status_code == 302


# ── T6 — 422 never echoes the submitted password ───────────────────────────


def test_422_does_not_echo_submitted_password():
    sentinel = "S3NT1NEL" * 20  # 160 chars, exceeds max_length=128
    response = client.post(
        LOGIN_URL, json={"email": "a@example.com", "password": sentinel}
    )
    assert response.status_code == 422
    assert sentinel not in response.text
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    errors = body["error"]["details"]["errors"]
    assert len(errors) >= 1
    # ctx (constraint bounds) is intentionally kept — only `input`/`url` are scrubbed.
    assert any("ctx" in e for e in errors)
    assert all("input" not in e and "url" not in e for e in errors)


# ── T7 — email normalization is unified across lockout key and DB lookup ──


def test_normalize_email_strips_and_lowers():
    assert normalize_email("  Arshad@Example.COM  ") == "arshad@example.com"
    assert normalize_email("arshad@example.com") == "arshad@example.com"


def test_router_uses_one_normalized_email_for_lookup_and_lockout(
    monkeypatch, no_backstop
):
    seen_lookup = []
    seen_lockout = []

    async def _fake_lookup(db, email_norm):
        seen_lookup.append(email_norm)
        return None

    async def _fake_assert_not_locked(email_norm):
        seen_lockout.append(email_norm)

    monkeypatch.setattr(routers_mod, "authenticate_with_password", _fake_lookup)
    monkeypatch.setattr(lockout_mod, "assert_not_locked", _fake_assert_not_locked)
    monkeypatch.setattr(lockout_mod, "record_failure", AsyncMock(return_value=None))
    _override_db(None)

    for raw_email in ("Arshad@Example.COM", "arshad@example.com"):
        client.post(LOGIN_URL, json={"email": raw_email, "password": "x"})

    assert seen_lookup == ["arshad@example.com", "arshad@example.com"]
    assert seen_lockout == ["arshad@example.com", "arshad@example.com"]


# ── T8 — Redis outage: global backstop fails OPEN ──────────────────────────


def test_global_backstop_fails_open_on_redis_outage(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    monkeypatch.setattr(
        rate_limit_mod,
        "get_redis",
        AsyncMock(side_effect=redis.exceptions.RedisError("down")),
    )
    # lockout uses .get() (assert_not_locked) and .delete() (clear_failures,
    # reached on this success path) — both need to be awaitable.
    fake_lockout_redis = MagicMock()
    fake_lockout_redis.get = AsyncMock(return_value=None)
    fake_lockout_redis.delete = AsyncMock(return_value=None)
    monkeypatch.setattr(
        lockout_mod, "get_redis", AsyncMock(return_value=fake_lockout_redis)
    )
    monkeypatch.setattr(password_mod, "_checkpw", AsyncMock(return_value=True))
    _override_db(_FakeUser("a@example.com", "somehash"))

    response = client.post(
        LOGIN_URL, json={"email": "a@example.com", "password": "correct"}
    )

    assert response.status_code == 200
    assert "token" in response.json()["data"]


# ── T9 — Redis outage: per-email lockout fails CLOSED ──────────────────────


def test_lockout_fails_closed_on_redis_outage(monkeypatch, no_backstop):
    monkeypatch.setattr(
        lockout_mod,
        "get_redis",
        AsyncMock(side_effect=redis.exceptions.RedisError("down")),
    )
    response = client.post(LOGIN_URL, json={"email": "a@example.com", "password": "x"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "login_temporarily_unavailable"
    assert "Retry-After" not in response.headers


# ── T9b — lockout THRESHOLD path (the actual brute-force guard), not just
# its Redis-outage escape hatch. Added post-gate: coverage review found
# every other test bypasses this module via the `no_lockout` fixture or
# only exercises the outage branch, leaving the module's actual job — the
# 429-at-5-failures enforcement — untested. ──────────────────────────────


@pytest.mark.asyncio
async def test_lockout_allows_below_threshold(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=str(lockout_mod._THRESHOLD - 1).encode())
    monkeypatch.setattr(lockout_mod, "get_redis", AsyncMock(return_value=fake_redis))
    await lockout_mod.assert_not_locked("a@example.com")  # must not raise


@pytest.mark.asyncio
async def test_lockout_raises_429_with_retry_after_at_threshold(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=str(lockout_mod._THRESHOLD).encode())
    monkeypatch.setattr(lockout_mod, "get_redis", AsyncMock(return_value=fake_redis))

    with pytest.raises(HTTPException) as exc_info:
        await lockout_mod.assert_not_locked("a@example.com")

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"]["code"] == "too_many_login_attempts"
    assert exc_info.value.headers["Retry-After"] == str(lockout_mod._WINDOW_SECONDS)


def test_record_failure_called_with_normalized_email_on_wrong_password(
    monkeypatch, no_backstop
):
    monkeypatch.setattr(lockout_mod, "assert_not_locked", AsyncMock(return_value=None))
    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(lockout_mod, "record_failure", spy)
    monkeypatch.setattr(password_mod, "_checkpw", AsyncMock(return_value=False))
    _override_db(_FakeUser("arshad@example.com", "somehash"))

    response = client.post(
        LOGIN_URL, json={"email": " Arshad@Example.COM ", "password": "wrong"}
    )

    assert response.status_code == 401
    spy.assert_awaited_once_with("arshad@example.com")


def test_clear_failures_called_with_normalized_email_on_success(
    monkeypatch, no_backstop
):
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    monkeypatch.setattr(lockout_mod, "assert_not_locked", AsyncMock(return_value=None))
    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(lockout_mod, "clear_failures", spy)
    monkeypatch.setattr(password_mod, "_checkpw", AsyncMock(return_value=True))
    _override_db(_FakeUser("arshad@example.com", "somehash"))

    response = client.post(
        LOGIN_URL, json={"email": " Arshad@Example.COM ", "password": "correct"}
    )

    assert response.status_code == 200
    spy.assert_awaited_once_with("arshad@example.com")


@pytest.mark.asyncio
async def test_record_failure_increments_and_sets_ttl_once(monkeypatch):
    fake_redis = MagicMock()
    fake_pipe = MagicMock()
    fake_pipe.incr = MagicMock()
    fake_pipe.expire = MagicMock()
    fake_pipe.execute = AsyncMock(return_value=None)
    fake_redis.pipeline = MagicMock(return_value=fake_pipe)
    monkeypatch.setattr(lockout_mod, "get_redis", AsyncMock(return_value=fake_redis))

    await lockout_mod.record_failure("a@example.com")

    key = lockout_mod._bucket_key("a@example.com")
    fake_pipe.incr.assert_called_once_with(key)
    fake_pipe.expire.assert_called_once_with(key, lockout_mod._WINDOW_SECONDS, nx=True)
    fake_pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_failures_deletes_bucket_key(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.delete = AsyncMock(return_value=None)
    monkeypatch.setattr(lockout_mod, "get_redis", AsyncMock(return_value=fake_redis))

    await lockout_mod.clear_failures("a@example.com")

    fake_redis.delete.assert_awaited_once_with(lockout_mod._bucket_key("a@example.com"))


@pytest.mark.parametrize("sentinel", ["0", "no", "No", "0 "])
def test_kill_switch_disabled_sentinels(monkeypatch, sentinel, no_backstop, no_lockout):
    monkeypatch.setenv("PASSWORD_AUTH_ENABLED", sentinel)
    response = client.post(LOGIN_URL, json={"email": "a@example.com", "password": "x"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "password_auth_disabled"


# ── T10 — OAuth CALLBACK leg survives a Redis outage ───────────────────────


def test_oauth_callback_survives_redis_outage(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://frontend.example.com")

    nonce = "outage-nonce"
    signed_state = routers_mod._make_signed_state(nonce)

    fake_redis = MagicMock()
    fake_redis.getdel = AsyncMock(side_effect=redis.exceptions.RedisError("down"))
    monkeypatch.setattr(routers_mod, "get_redis", AsyncMock(return_value=fake_redis))

    monkeypatch.setattr(
        GoogleOAuthProvider, "exchange_code", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(
        GoogleOAuthProvider, "fetch_user_info", AsyncMock(return_value=MagicMock())
    )
    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    monkeypatch.setattr(
        routers_mod, "upsert_user_from_oauth", AsyncMock(return_value=fake_user)
    )

    with TestClient(app, follow_redirects=False) as tc:
        tc.cookies.set("oauth_login_nonce", nonce)
        response = tc.get(
            f"/api/v1/auth/google/callback?code=fake-code&state={signed_state}"
        )

    assert response.status_code == 302
    assert "token=" in response.headers["location"]


def test_oauth_replay_protection_intact_when_redis_healthy(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://frontend.example.com")

    nonce = "healthy-nonce"
    signed_state = routers_mod._make_signed_state(nonce)

    store: dict[str, str] = {f"login_oauth_state:{nonce}": "1"}
    fake_redis = MagicMock()

    async def _getdel(key):
        return store.pop(key, None)

    fake_redis.getdel = _getdel
    monkeypatch.setattr(routers_mod, "get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(
        GoogleOAuthProvider, "exchange_code", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(
        GoogleOAuthProvider, "fetch_user_info", AsyncMock(return_value=MagicMock())
    )
    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    monkeypatch.setattr(
        routers_mod, "upsert_user_from_oauth", AsyncMock(return_value=fake_user)
    )

    with TestClient(app, follow_redirects=False) as tc:
        tc.cookies.set("oauth_login_nonce", nonce)
        first = tc.get(
            f"/api/v1/auth/google/callback?code=fake-code&state={signed_state}"
        )
        second = tc.get(
            f"/api/v1/auth/google/callback?code=fake-code&state={signed_state}"
        )

    assert first.status_code == 302
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "invalid_state"


# ── T12 — bcrypt runs off the event loop ────────────────────────────────────


@pytest.mark.asyncio
async def test_dummy_verify_runs_in_threadpool(monkeypatch):
    spy = AsyncMock(wraps=password_mod.run_in_threadpool)
    monkeypatch.setattr(password_mod, "run_in_threadpool", spy)
    await password_mod.dummy_verify("anything")
    assert spy.call_count == 1


@pytest.mark.asyncio
async def test_verify_password_runs_in_threadpool(monkeypatch):
    hashed = await password_mod.hash_password("correct-horse")
    spy = AsyncMock(wraps=password_mod.run_in_threadpool)
    monkeypatch.setattr(password_mod, "run_in_threadpool", spy)
    ok = await password_mod.verify_password("correct-horse", hashed)
    assert ok is True
    assert spy.call_count == 1
