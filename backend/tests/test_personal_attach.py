"""Tests for the authenticated personal OAuth attach flow (FEAT-156).

Non-pg tests stub the DB and Redis; @pytest.mark.pg tests write real
oauth_accounts/oauth_tokens/integrations rows (need TEST_DATABASE_URL).
"""

from __future__ import annotations

import json
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import src.integrations.personal._attach as attach
import src.integrations.personal._oauth_base as oauth_base
import src.integrations.personal._pending as pending_mod
from sqlalchemy import select
from src.auth.dependencies import get_current_user
from src.auth.providers.base import OAuthError, OAuthTokenBundle, OAuthUserInfo
from src.integrations.base import IntegrationError
from src.main import app
from src.models.database import get_db
from src.models.integration import Integration
from src.models.oauth_account import OAuthAccount
from src.models.oauth_token import OAuthToken
from src.models.user import User

FRONTEND = "https://app.example.com"
BACKEND = "https://api.example.com"
SECRET_TOKEN = "gho_super_secret_access_token"


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def getdel(self, key):
        return self.store.pop(key, None)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


class _User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.email = "owner@example.com"


class FakeProvider:
    def __init__(self, provider_user_id: str = "gh-1") -> None:
        self.uid = provider_user_id

    async def exchange_code(self, code):
        return OAuthTokenBundle(
            access_token=SECRET_TOKEN,
            refresh_token=None,
            expires_at=None,
            scopes=["read:user", "repo"],
        )

    async def fetch_user_info(self, access_token):
        return OAuthUserInfo(
            provider_user_id=self.uid,
            email="me@example.com",
            name="Me",
            avatar_url=None,
        )


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", FRONTEND)
    monkeypatch.setenv("BACKEND_URL", BACKEND)
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "gh-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "gh-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "g-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "g-secret")
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")


@pytest.fixture
def redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(oauth_base, "get_redis", AsyncMock(return_value=fake))
    monkeypatch.setattr(pending_mod, "get_redis", AsyncMock(return_value=fake))
    return fake


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _fake_db(scalar_values=None):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=scalar_values or [None])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


def _use(user, db) -> None:
    async def _u():
        return user

    async def _d():
        yield db

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_db] = _d


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _begin_attach(redis: FakeRedis, user, slug="github", provider="github"):
    """Run the real authenticated connect and return its `state`."""
    result = await attach.start_personal_oauth_attach(
        user_id=str(user.id), slug=slug, oauth_provider=provider
    )
    q = parse_qs(urlparse(result.redirect_url).query)
    return q["state"][0], result


def _pending_id(location: str) -> str:
    return parse_qs(urlparse(location).query)["pending"][0]


# ── connect ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_without_account_returns_authorize_url_bound_to_user(redis):
    user = _User()
    _use(user, _fake_db([None]))
    async with _client() as c:
        r = await c.post("/api/v1/integrations/github/connect", json={})
    assert r.status_code == 200
    url = r.json()["data"]["redirect_url"]
    assert url.startswith("https://github.com/login/oauth/authorize")
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == [
        f"{BACKEND}/api/v1/auth/github/callback/attach"
    ]
    stored = redis.store[f"int_oauth_state:{q['state'][0]}"]
    assert str(user.id) in stored and "github" in stored


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug,host",
    [
        ("github", "github.com"),
        ("gmail", "accounts.google.com"),
        ("google_calendar", "accounts.google.com"),
        ("google_drive", "accounts.google.com"),
        ("google_tasks", "accounts.google.com"),
        ("youtube", "accounts.google.com"),
    ],
)
async def test_all_six_providers_return_authorize_url_not_login_redirect(
    redis, slug, host
):
    _use(_User(), _fake_db([None]))
    async with _client() as c:
        r = await c.post(f"/api/v1/integrations/{slug}/connect", json={})
    assert r.status_code == 200
    url = r.json()["data"]["redirect_url"]
    assert urlparse(url).netloc == host
    assert not url.startswith(FRONTEND)


@pytest.mark.asyncio
async def test_connect_with_existing_account_unchanged(redis):
    account = MagicMock()
    _use(_User(), _fake_db([account, None]))
    async with _client() as c:
        r = await c.post("/api/v1/integrations/github/connect", json={})
    data = r.json()["data"]
    assert r.status_code == 200
    assert data["redirect_url"] is None
    assert not [k for k in redis.store if k.startswith("int_oauth_state:")]


# ── anonymous callback ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_callback_valid_state_creates_pending_and_redirects(redis):
    user = _User()
    state, _ = await _begin_attach(redis, user)
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/github/callback",
            params={"code": "the-code", "state": state},
            follow_redirects=False,
        )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(f"{FRONTEND}/integrations/oauth-complete?pending=")
    assert "slug=github" in loc and "the-code" not in loc
    pending = json.loads(redis.store[f"attach_pending:{_pending_id(loc)}"])
    assert pending["user_id"] == str(user.id)
    assert "the-code" not in json.dumps(pending)
    assert f"int_oauth_state:{state}" not in redis.store


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["unknown", "replayed", "missing"])
async def test_callback_bad_state_fails_closed(redis, variant):
    user = _User()
    state, _ = await _begin_attach(redis, user)
    params = {"code": "c", "state": "nope"}
    async with _client() as c:
        path = "/api/v1/integrations/personal/attach/github/callback"
        if variant == "replayed":
            await c.get(path, params={"code": "c", "state": state})
            params = {"code": "c", "state": state}
        if variant == "missing":
            params = {"code": "c"}
        before = {k for k in redis.store if k.startswith("attach_pending:")}
        r = await c.get(path, params=params, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == f"{FRONTEND}/integrations?error=invalid_state"
    after = {k for k in redis.store if k.startswith("attach_pending:")}
    assert after == before


@pytest.mark.asyncio
async def test_callback_state_for_other_provider_rejected(redis):
    state, _ = await _begin_attach(redis, _User(), "gmail", "google")
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/github/callback",
            params={"code": "c", "state": state},
            follow_redirects=False,
        )
    assert r.headers["location"].endswith("error=invalid_state")


@pytest.mark.asyncio
async def test_callback_provider_error_redirects_with_slug(redis):
    state, _ = await _begin_attach(redis, _User())
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/github/callback",
            params={"error": "access_denied", "state": state},
            follow_redirects=False,
        )
    assert r.headers["location"] == (
        f"{FRONTEND}/integrations?error=access_denied&slug=github"
    )


@pytest.mark.asyncio
async def test_callback_unsupported_provider_400(redis):
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/evil/callback",
            params={"code": "c", "state": "s"},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_redis_failure_after_state_consumed_shows_error(
    redis, monkeypatch
):
    state, _ = await _begin_attach(redis, _User())
    monkeypatch.setattr(
        pending_mod, "store_attach_pending", AsyncMock(side_effect=RuntimeError("down"))
    )
    # the router imports the symbol lazily from the module, so patch applies
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/github/callback",
            params={"code": "c", "state": state},
            follow_redirects=False,
        )
    assert r.headers["location"] == (
        f"{FRONTEND}/integrations?error=internal_error&slug=github"
    )


# ── authenticated completion ─────────────────────────────────────────────


async def _make_pending(redis, owner) -> str:
    return await attach.store_attach_pending(
        user_id=str(owner.id), slug="github", oauth_provider="github", code="c0de"
    )


@pytest.mark.asyncio
async def test_complete_requires_authentication(redis):
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": "x", "slug": "github"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_complete_expired_pending(redis):
    _use(_User(), _fake_db())
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": "gone", "slug": "github"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "pending_expired"


@pytest.mark.asyncio
async def test_complete_by_other_user_rejected_links_nothing_and_not_burned(redis):
    owner, attacker_victim = _User(), _User()
    pid = await _make_pending(redis, owner)
    db = _fake_db()
    _use(attacker_victim, db)
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "github"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "state_user_mismatch"
    db.add.assert_not_called()
    db.commit.assert_not_called()
    assert f"attach_pending:{pid}" in redis.store


@pytest.mark.asyncio
async def test_complete_slug_mismatch(redis):
    owner = _User()
    pid = await _make_pending(redis, owner)
    _use(owner, _fake_db())
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "gmail"},
        )
    assert r.json()["error"]["code"] == "slug_mismatch"


# ── real Postgres ────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.pg
async def test_complete_happy_path_links_only_initiating_user(
    redis, pg_session, committed_user, monkeypatch, caplog
):
    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: FakeProvider())
    pid = await _make_pending(redis, committed_user)
    _use(committed_user, pg_session)
    caplog.set_level(logging.DEBUG)
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "github"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {
        "slug": "github",
        "connected": True,
        "provider_email": "me@example.com",
    }
    acct = await pg_session.scalar(
        select(OAuthAccount).where(OAuthAccount.user_id == committed_user.id)
    )
    assert acct is not None and acct.provider == "github"
    tok = await pg_session.scalar(
        select(OAuthToken).where(OAuthToken.oauth_account_id == acct.id)
    )
    assert tok is not None
    assert SECRET_TOKEN.encode() not in bytes(tok.encrypted_access_token)
    integ = await pg_session.scalar(
        select(Integration).where(
            Integration.user_id == committed_user.id, Integration.slug == "github"
        )
    )
    assert integ is not None and integ.status == "connected"
    assert SECRET_TOKEN not in caplog.text and "c0de" not in caplog.text
    # replay of the same pending key is rejected
    async with _client() as c:
        again = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "github"},
        )
    assert again.json()["error"]["code"] == "pending_expired"


@pytest.mark.asyncio
@pytest.mark.pg
async def test_cross_user_complete_writes_nothing_in_postgres(
    redis, pg_session, committed_user, monkeypatch
):
    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: FakeProvider())
    other = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:6]}@example.com")
    pg_session.add(other)
    await pg_session.flush()
    pid = await _make_pending(redis, committed_user)
    _use(other, pg_session)
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "github"},
        )
    assert r.json()["error"]["code"] == "state_user_mismatch"
    rows = (await pg_session.scalars(select(OAuthAccount))).all()
    assert not [a for a in rows if a.user_id in (other.id, committed_user.id)]


@pytest.mark.asyncio
@pytest.mark.pg
async def test_attach_is_idempotent(pg_session, committed_user, monkeypatch):
    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: FakeProvider())
    for _ in range(2):
        await attach.complete_personal_attach(
            user=committed_user,
            slug="github",
            oauth_provider="github",
            code="c",
            db=pg_session,
        )
    accounts = (
        await pg_session.scalars(
            select(OAuthAccount).where(OAuthAccount.user_id == committed_user.id)
        )
    ).all()
    assert len(accounts) == 1


@pytest.mark.asyncio
@pytest.mark.pg
async def test_account_already_linked_to_other_user(
    pg_session, committed_user, monkeypatch
):
    owner = User(id=uuid.uuid4(), email=f"w-{uuid.uuid4().hex[:6]}@example.com")
    pg_session.add(owner)
    await pg_session.flush()
    pg_session.add(
        OAuthAccount(
            user_id=owner.id,
            provider="github",
            provider_user_id="gh-1",
            provider_email="w@example.com",
        )
    )
    await pg_session.flush()
    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: FakeProvider())
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=committed_user,
            slug="github",
            oauth_provider="github",
            code="c",
            db=pg_session,
        )
    assert exc.value.code == "account_already_linked"
    mine = await pg_session.scalar(
        select(OAuthAccount).where(OAuthAccount.user_id == committed_user.id)
    )
    assert mine is None


@pytest.mark.asyncio
async def test_exchange_failure_maps_to_token_exchange_failed(monkeypatch):
    class Boom(FakeProvider):
        async def exchange_code(self, code):
            raise httpx.ConnectError("net")

    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: Boom())
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=_User(),
            slug="github",
            oauth_provider="github",
            code="c",
            db=_fake_db(),
        )
    assert exc.value.code == "token_exchange_failed"


# ── additional negative / edge coverage ─────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_callback_never_touches_database(redis):
    """The unauthenticated callback must link nothing: it may not open a DB session."""

    async def _boom():
        raise AssertionError("anonymous callback must not use the database")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = _boom
    state, _ = await _begin_attach(redis, _User())
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/github/callback",
            params={"code": "c", "state": state},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert "/integrations/oauth-complete?pending=" in r.headers["location"]


@pytest.mark.asyncio
async def test_callback_state_lookup_failure_shows_error_not_json(redis, monkeypatch):
    monkeypatch.setattr(
        oauth_base,
        "consume_oauth_state",
        AsyncMock(side_effect=RuntimeError("redis down")),
    )
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/github/callback",
            params={"code": "c", "state": "s"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert r.headers["location"] == f"{FRONTEND}/integrations?error=internal_error"


@pytest.mark.asyncio
async def test_callback_provider_error_is_encoded_truncated_and_cannot_inject_params(
    redis,
):
    state, _ = await _begin_attach(redis, _User())
    evil = "x" * 100 + "&connected=github#frag"
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/personal/attach/github/callback",
            params={"error": evil, "state": state},
            follow_redirects=False,
        )
    loc = r.headers["location"]
    assert loc.startswith(f"{FRONTEND}/integrations?")
    q = parse_qs(urlparse(loc).query)
    assert set(q) == {"error", "slug"}
    assert len(q["error"][0]) <= 64


@pytest.mark.asyncio
async def test_complete_with_unparseable_owner_id_is_mismatch(redis):
    user = _User()
    pid = await _make_pending(redis, user)
    key = f"attach_pending:{pid}"
    rec = json.loads(redis.store[key])
    rec["user_id"] = "not-a-uuid"
    redis.store[key] = json.dumps(rec)
    db = _fake_db()
    _use(user, db)
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "github"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "state_user_mismatch"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_complete_lost_consume_race_exchanges_nothing(redis, monkeypatch):
    """Concurrent completes both peek; only the winning delete may proceed."""
    owner = _User()
    pid = await _make_pending(redis, owner)
    monkeypatch.setattr(
        pending_mod, "consume_attach_pending", AsyncMock(return_value=False)
    )
    exchange = AsyncMock(side_effect=AssertionError("must not exchange"))
    monkeypatch.setattr(attach, "complete_personal_attach", exchange)
    db = _fake_db()
    _use(owner, db)
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "github"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "pending_expired"
    exchange.assert_not_called()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_complete_undecryptable_code_returns_pending_corrupt(redis, monkeypatch):
    import base64

    owner = _User()
    pid = await _make_pending(redis, owner)
    key = f"attach_pending:{pid}"
    rec = json.loads(redis.store[key])
    rec["code_enc"] = base64.b64encode(b"garbage-not-fernet").decode()
    redis.store[key] = json.dumps(rec)
    exchange = AsyncMock(side_effect=AssertionError("must not exchange"))
    monkeypatch.setattr(attach, "complete_personal_attach", exchange)
    db = _fake_db()
    _use(owner, db)
    async with _client() as c:
        r = await c.post(
            "/api/v1/integrations/oauth-complete",
            json={"pending_key": pid, "slug": "github"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "pending_corrupt"
    exchange.assert_not_called()
    assert f"attach_pending:{pid}" not in redis.store


@pytest.mark.asyncio
async def test_second_distinct_provider_account_refused_without_writes(monkeypatch):
    monkeypatch.setattr(
        attach, "_get_provider_for_attach", lambda p: FakeProvider("gh-new")
    )
    # 1st scalar: no row for this provider_user_id; 2nd: user already has one.
    db = _fake_db([None, uuid.uuid4()])
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=_User(), slug="github", oauth_provider="github", code="c", db=db
        )
    assert exc.value.code == "provider_already_connected"
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_exchange_failure_does_not_log_secrets(monkeypatch, caplog):
    class Leaky(FakeProvider):
        async def exchange_code(self, code):
            raise OAuthError("bad", f"echo {SECRET_TOKEN} code={code}")

    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: Leaky())
    caplog.set_level(logging.DEBUG)
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=_User(),
            slug="github",
            oauth_provider="github",
            code="s3cretcode",
            db=_fake_db(),
        )
    assert exc.value.code == "token_exchange_failed"
    assert SECRET_TOKEN not in caplog.text and "s3cretcode" not in caplog.text
    assert SECRET_TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_connect_without_backend_url_fails_closed_and_stores_no_state(
    redis, monkeypatch
):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    with pytest.raises((RuntimeError, IntegrationError)):
        await attach.start_personal_oauth_attach(
            user_id=str(uuid.uuid4()), slug="github", oauth_provider="github"
        )
    assert not [k for k in redis.store if k.startswith("int_oauth_state:")]


@pytest.mark.asyncio
async def test_generic_oauth_callback_error_is_encoded_and_cannot_inject_params(redis):
    evil = "denied&connected=shopify#frag"
    async with _client() as c:
        r = await c.get(
            "/api/v1/integrations/oauth/shopify/callback",
            params={"error": evil},
            follow_redirects=False,
        )
    loc = r.headers["location"]
    assert loc.startswith(f"{FRONTEND}/integrations?")
    q = parse_qs(urlparse(loc).query)
    assert set(q) == {"error", "slug"}
    assert q["error"] == [evil]
    assert "connected" not in q


# ── GitHub redirect URI sits under the registered login callback ─────────


def test_github_attach_redirect_uri_is_under_login_callback():
    uri = attach.attach_redirect_uri("github")
    assert uri == f"{BACKEND}/api/v1/auth/github/callback/attach"
    assert uri.startswith(f"{BACKEND}/api/v1/auth/github/callback")


def test_google_attach_redirect_uri_unchanged():
    assert attach.attach_redirect_uri("google") == (
        f"{BACKEND}/api/v1/integrations/personal/attach/google/callback"
    )


@pytest.mark.asyncio
async def test_github_alias_callback_parks_pending_and_redirects(redis):
    user = _User()
    state, _ = await _begin_attach(redis, user)
    async with _client() as c:
        r = await c.get(
            "/api/v1/auth/github/callback/attach",
            params={"code": "abc", "state": state},
            follow_redirects=False,
        )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(f"{FRONTEND}/integrations/oauth-complete?pending=")
    assert "abc" not in loc


@pytest.mark.asyncio
async def test_github_alias_callback_rejects_unknown_state(redis):
    async with _client() as c:
        r = await c.get(
            "/api/v1/auth/github/callback/attach",
            params={"code": "abc", "state": "nope"},
            follow_redirects=False,
        )
    assert parse_qs(urlparse(r.headers["location"]).query)["error"] == ["invalid_state"]


# ── failure handling around the exchange and the final save ──────────────


@pytest.mark.asyncio
async def test_missing_provider_env_is_provider_not_configured(monkeypatch):
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=_User(), slug="github", oauth_provider="github", code="c", db=_fake_db()
        )
    assert exc.value.code == "provider_not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize("err", [ValueError("not json"), KeyError("id")])
async def test_malformed_provider_reply_maps_to_token_exchange_failed(monkeypatch, err):
    class Bad(FakeProvider):
        async def fetch_user_info(self, access_token):
            raise err

    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: Bad())
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=_User(), slug="github", oauth_provider="github", code="c", db=_fake_db()
        )
    assert exc.value.code == "token_exchange_failed"


@pytest.mark.asyncio
async def test_unverified_provider_email_gets_its_own_code(monkeypatch):
    class NoEmail(FakeProvider):
        async def fetch_user_info(self, access_token):
            raise OAuthError("no_verified_email", "no verified primary email")

    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: NoEmail())
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=_User(), slug="github", oauth_provider="github", code="c", db=_fake_db()
        )
    assert exc.value.code == "provider_email_unverified"


@pytest.mark.asyncio
async def test_integration_save_failure_after_tokens_is_clear_and_rolls_back(monkeypatch):
    from sqlalchemy.exc import DBAPIError

    monkeypatch.setattr(attach, "_get_provider_for_attach", lambda p: FakeProvider())
    monkeypatch.setattr(attach, "_attach_account_to_user", AsyncMock())
    monkeypatch.setattr(
        attach,
        "upsert_personal_integration",
        AsyncMock(side_effect=DBAPIError("x", {}, Exception("boom"))),
    )
    db = _fake_db()
    db.rollback = AsyncMock()
    with pytest.raises(IntegrationError) as exc:
        await attach.complete_personal_attach(
            user=_User(), slug="github", oauth_provider="github", code="c", db=db
        )
    assert exc.value.code == "integration_save_failed"
    db.rollback.assert_awaited()
