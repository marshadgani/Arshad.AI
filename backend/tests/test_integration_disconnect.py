"""Disconnect must actually remove the stored credentials the UI promises to
remove (FEAT-145), without touching the user's login tokens."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
import redis.exceptions
from src.integrations.base import IntegrationProvider
from src.integrations.personal import apple_health
from src.integrations.registry import INTEGRATION_REGISTRY, get_provider


class DB:
    def __init__(self, scalar_result=None):
        self.statements = []
        self.commits = 0
        self._scalar_result = scalar_result

    async def execute(self, stmt):
        self.statements.append(stmt)

    async def scalar(self, _stmt):
        return self._scalar_result

    async def commit(self):
        self.commits += 1

    def sql(self):
        return [str(s.compile()) for s in self.statements]

    def bound(self):
        return [list(s.compile().params.values()) for s in self.statements]


def integration(**overrides):
    base = {"id": uuid.uuid4(), "status": "connected", "last_error": "old error"}
    return SimpleNamespace(**{**base, **overrides})


def run(coro):
    return asyncio.run(coro)


class Plain(IntegrationProvider):
    """Minimal provider that uses the default disconnect."""

    slug = "plain"
    kind = "static"
    display_name = "Plain"
    category = "x"
    description = "x"
    docs_url = ""
    icon = ""

    async def connect(self, **_kw): ...
    async def sync(self, **_kw): ...
    async def status(self, **_kw): ...


def test_default_disconnect_deletes_oauth_tokens_and_api_keys_for_that_integration():
    db, item = DB(), integration()
    run(Plain().disconnect(integration=item, db=db))
    sql = " ".join(db.sql())
    assert "DELETE FROM integration_oauth_tokens" in sql
    assert "DELETE FROM api_key_credentials" in sql
    assert all(item.id in params for params in db.bound())


def test_default_disconnect_marks_disconnected_clears_error_and_commits_once():
    db, item = DB(), integration()
    run(Plain().disconnect(integration=item, db=db))
    assert item.status == "disconnected"
    assert item.last_error is None
    assert db.commits == 1


def test_default_disconnect_never_touches_the_users_login_tokens():
    db = DB()
    run(Plain().disconnect(integration=integration(), db=db))
    sql = " ".join(db.sql())
    assert "oauth_tokens" not in sql.replace("integration_oauth_tokens", "")
    assert "oauth_accounts" not in sql


def test_only_apple_health_overrides_disconnect_so_all_others_delete_credentials():
    overriding = {
        slug
        for slug, provider in INTEGRATION_REGISTRY.items()
        if type(provider).disconnect is not IntegrationProvider.disconnect
    }
    assert overriding <= {"apple_health"}


class FakeRedis:
    def __init__(self, fail=False):
        self.deleted = []
        self.fail = fail

    async def delete(self, key):
        if self.fail:
            raise redis.exceptions.ConnectionError("down")
        self.deleted.append(key)


def _apple(monkeypatch, redis_client):
    async def fake_get_redis():
        return redis_client

    monkeypatch.setattr(apple_health, "get_redis", fake_get_redis)
    return get_provider("apple_health")


def test_apple_health_disconnect_revokes_token_purges_snapshot_and_deletes_credentials(
    monkeypatch,
):
    fake = FakeRedis()
    provider = _apple(monkeypatch, fake)
    token_row = SimpleNamespace(revoked_at=None)
    db, item = DB(scalar_result=token_row), integration()
    run(provider.disconnect(integration=item, db=db))
    assert token_row.revoked_at is not None
    assert fake.deleted == [f"apple_health:snapshot:{item.id}"]
    assert any("DELETE FROM api_key_credentials" in s for s in db.sql())
    assert item.status == "disconnected"


def test_apple_health_disconnect_still_completes_when_redis_is_down(monkeypatch):
    provider = _apple(monkeypatch, FakeRedis(fail=True))
    db, item = DB(scalar_result=None), integration()
    run(provider.disconnect(integration=item, db=db))
    assert item.status == "disconnected"
    assert db.commits == 1


@pytest.mark.parametrize("has_token", [True, False])
def test_apple_health_disconnect_handles_a_missing_ingest_token(monkeypatch, has_token):
    provider = _apple(monkeypatch, FakeRedis())
    token = SimpleNamespace(revoked_at=None) if has_token else None
    item = integration()
    run(provider.disconnect(integration=item, db=DB(scalar_result=token)))
    assert item.status == "disconnected"


# ── route level: POST /{slug}/disconnect ──────────────────────────────


class RecordingProvider:
    def __init__(self):
        self.disconnected = []

    async def disconnect(self, *, integration, db):
        self.disconnected.append(integration)


def _route(monkeypatch, found, user_email_allowed=True):
    from src.integrations import routers

    provider = RecordingProvider()

    async def fake_find(_slug, _user, _db):
        return found

    monkeypatch.setattr(routers, "_require_provider", lambda _slug: provider)
    monkeypatch.setattr(routers, "_find_user_integration", fake_find)
    monkeypatch.setattr(routers, "is_email_allowed", lambda _email: user_email_allowed)
    return routers, provider


USER = SimpleNamespace(email="owner@example.com")


def test_route_reports_already_disconnected_when_there_is_nothing_to_disconnect(
    monkeypatch,
):
    routers, provider = _route(monkeypatch, None)
    out = run(routers.disconnect_integration("github", USER, DB()))
    assert out == {"data": {"status": "already_disconnected"}}
    assert provider.disconnected == []


def test_route_disconnects_the_callers_own_integration(monkeypatch):
    item = integration(user_id=uuid.uuid4())
    routers, provider = _route(monkeypatch, item)
    out = run(routers.disconnect_integration("github", USER, DB()))
    assert out == {"data": {"status": "disconnected"}}
    assert provider.disconnected == [item]


def test_route_refuses_a_shared_integration_for_a_user_who_is_not_the_owner(
    monkeypatch,
):
    from fastapi import HTTPException

    shared = integration(user_id=None)
    routers, provider = _route(monkeypatch, shared, user_email_allowed=False)
    with pytest.raises(HTTPException):
        run(routers.disconnect_integration("stripe", USER, DB()))
    assert provider.disconnected == []


def test_route_lets_the_owner_disconnect_a_shared_integration(monkeypatch):
    shared = integration(user_id=None)
    routers, provider = _route(monkeypatch, shared)
    run(routers.disconnect_integration("stripe", USER, DB()))
    assert provider.disconnected == [shared]


def test_apple_health_revokes_the_token_before_clearing_the_cache(monkeypatch):
    order = []

    class OrderedRedis:
        async def delete(self, _key):
            order.append("purge")

    class OrderedDB(DB):
        async def commit(self):
            order.append("commit")
            await super().commit()

    token_row = SimpleNamespace(revoked_at=None)
    provider = _apple(monkeypatch, OrderedRedis())
    run(
        provider.disconnect(
            integration=integration(), db=OrderedDB(scalar_result=token_row)
        )
    )
    assert token_row.revoked_at is not None
    assert order == ["commit", "purge"]


def test_apple_health_purge_survives_a_non_redis_error(monkeypatch):
    async def broken_get_redis():
        raise RuntimeError("no redis configured")

    monkeypatch.setattr(apple_health, "get_redis", broken_get_redis)
    item = integration()
    run(
        get_provider("apple_health").disconnect(
            integration=item, db=DB(scalar_result=None)
        )
    )
    assert item.status == "disconnected"
