"""Tests for the Apple Health push-ingest DB/cache boundary.

Covers the part that matters most for the hard constraint in this
feature: biometric values must never reach Postgres, only a
short-TTL Redis cache; and the ingest token is stored only as a
SHA-256 hash, never in cleartext, with rotation replacing (not
appending to) the row.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.api.v1 import apple_health as apple_health_router_module
from src.auth.dependencies import get_current_user
from src.integrations.base import ConnectResult
from src.integrations.personal.apple_health import (
    AppleHealthIntegration,
    hash_ingest_token,
)
from src.main import app
from src.models.database import get_db
from src.models.integration import Integration, IntegrationIngestToken

USER_ID = uuid.uuid4()


class _FakeUser:
    id = USER_ID


class _FakeRedis:
    """In-memory stand-in for the redis-py async client, just the subset
    of the interface this feature touches (get/set/incr/expire)."""

    def __init__(self):
        self.store: dict[str, tuple[str, int | None]] = {}

    async def get(self, key):
        entry = self.store.get(key)
        return entry[0] if entry else None

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)

    async def incr(self, key):
        current = int(self.store.get(key, ("0", None))[0]) + 1
        ttl = self.store.get(key, (None, None))[1]
        self.store[key] = (str(current), ttl)
        return current

    async def expire(self, key, seconds, nx=False):
        value, ttl = self.store.get(key, (None, None))
        if nx and ttl is not None:
            return
        self.store[key] = (value, seconds)


# ── connect(): token hashing + rotation ────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_stores_hash_not_cleartext_and_returns_cleartext_once():
    provider = AppleHealthIntegration()
    db = MagicMock()
    db.scalar = AsyncMock(
        side_effect=[None, None]
    )  # no existing integration, no existing token row
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await provider.connect(user=_FakeUser(), db=db, payload={})

    assert isinstance(result, ConnectResult)
    assert result.ingest_token is not None
    added = [call.args[0] for call in db.add.call_args_list]
    token_rows = [row for row in added if isinstance(row, IntegrationIngestToken)]
    assert len(token_rows) == 1
    stored_hash = token_rows[0].token_hash
    assert stored_hash != result.ingest_token
    assert stored_hash == hash_ingest_token(result.ingest_token)


@pytest.mark.asyncio
async def test_connect_rotation_replaces_hash_in_place_not_a_new_row():
    provider = AppleHealthIntegration()
    integration = Integration(
        id=uuid.uuid4(), user_id=USER_ID, slug="apple_health", kind="personal_push"
    )
    existing_token_row = IntegrationIngestToken(
        integration_id=integration.id, token_hash="old_hash"
    )
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[integration, existing_token_row])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await provider.connect(user=_FakeUser(), db=db, payload={})

    db.add.assert_not_called()  # rotated in place, not a second row
    assert existing_token_row.token_hash == hash_ingest_token(result.ingest_token)
    assert existing_token_row.revoked_at is None


# ── ingest endpoint: DB write boundary ─────────────────────────────────────


@pytest.fixture
def client():
    async def _override_user():
        return _FakeUser()

    app.dependency_overrides[get_current_user] = _override_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _wire_db(monkeypatch, integration=None, token_row=None):
    async def _override_db():
        db = MagicMock()
        db.scalar = AsyncMock(side_effect=[token_row, integration])
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _override_db


def test_ingest_rejects_invalid_token(client, monkeypatch):
    _wire_db(monkeypatch, integration=None, token_row=None)
    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 55},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_ingest_token"


def test_ingest_caches_snapshot_and_never_writes_biometrics_to_config(
    client, monkeypatch
):
    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="connected",
        config={},
    )
    real_token = "a-real-shortcut-token"
    token_row = IntegrationIngestToken(
        integration_id=integration.id, token_hash=hash_ingest_token(real_token)
    )
    _wire_db(monkeypatch, integration=integration, token_row=token_row)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=fake_redis)
    )

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 55, "sleep_hours": 7.5},
        headers={"Authorization": f"Bearer {real_token}"},
    )

    assert resp.status_code == 200
    # Biometric values landed in Redis (with a TTL), not in the Integration
    # row's JSONB config — config must stay untouched by this endpoint.
    assert integration.config == {}
    assert any("apple_health:snapshot:" in k for k in fake_redis.store)
    stored_value, ttl = next(v for k, v in fake_redis.store.items() if "snapshot" in k)
    assert ttl is not None and ttl > 0
    assert integration.last_synced_at is not None

    # The stored value is AES-GCM ciphertext behind the "AH1:" envelope
    # prefix, never the cleartext biometric reading. Checking for the
    # field name (rather than the numeric value, which is short enough to
    # collide by chance in random base64 output) proves it isn't the raw
    # JSON serialisation.
    assert stored_value.startswith("AH1:")
    assert "resting_heart_rate" not in stored_value
    assert "sleep_hours" not in stored_value


def test_ingest_dashboard_round_trip_decrypts_to_same_values(client, monkeypatch):
    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="connected",
        config={},
    )
    real_token = "a-real-shortcut-token"
    token_row = IntegrationIngestToken(
        integration_id=integration.id, token_hash=hash_ingest_token(real_token)
    )
    _wire_db(monkeypatch, integration=integration, token_row=token_row)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=fake_redis)
    )

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 55, "sleep_hours": 7.5},
        headers={"Authorization": f"Bearer {real_token}"},
    )
    assert resp.status_code == 200

    app.dependency_overrides[get_current_user] = lambda: _FakeUser()

    async def _override_dashboard_db():
        db = MagicMock()
        db.scalar = AsyncMock(return_value=integration)
        yield db

    app.dependency_overrides[get_db] = _override_dashboard_db

    dash_resp = client.get("/api/v1/apple-health/dashboard")
    assert dash_resp.status_code == 200
    body = dash_resp.json()["data"]
    assert body["resting_heart_rate"] == 55
    assert body["sleep_hours"] == 7.5
    assert body["stale"] is False


def test_dashboard_corrupt_cache_value_returns_stale_never_500(client, monkeypatch):
    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="connected",
    )

    async def _override_db():
        db = MagicMock()
        db.scalar = AsyncMock(return_value=integration)
        yield db

    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[get_db] = _override_db

    fake_redis = _FakeRedis()
    fake_redis.store["apple_health:snapshot:" + str(integration.id)] = (
        "AH1:not-valid-base64-ciphertext",
        21600,
    )
    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=fake_redis)
    )

    resp = client.get("/api/v1/apple-health/dashboard")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True
    assert body["stale"] is True


def test_ingest_rejects_disconnected_integration(client, monkeypatch):
    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="disconnected",
    )
    real_token = "a-real-shortcut-token"
    token_row = IntegrationIngestToken(
        integration_id=integration.id, token_hash=hash_ingest_token(real_token)
    )
    _wire_db(monkeypatch, integration=integration, token_row=token_row)

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 55},
        headers={"Authorization": f"Bearer {real_token}"},
    )
    assert resp.status_code == 401


# ── status()/sync(): the _has_recent_push() path ────────────────────────────
#
# Regression coverage for a missing `snapshot_store` import in
# integrations/personal/apple_health.py: `_has_recent_push` referenced
# `snapshot_store.has_snapshot(...)` without importing the `snapshot_store`
# submodule, so every call to status() or sync() raised NameError. The
# ingest-endpoint tests above never exercise this path, which is exactly why
# it went undetected — status()/sync() only run through the provider
# directly, not through api/v1/apple_health.py.


@pytest.mark.asyncio
async def test_status_reports_recent_push_without_raising(monkeypatch):
    import src.integrations.personal.apple_health as provider_module

    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="connected",
    )
    fake_redis = _FakeRedis()
    await fake_redis.set(f"apple_health:snapshot:{integration.id}", "AH1:fake", ex=100)
    monkeypatch.setattr(
        provider_module, "get_redis", AsyncMock(return_value=fake_redis)
    )

    provider = AppleHealthIntegration()
    report = await provider.status(integration=integration, db=MagicMock())

    assert report.extra["has_recent_push"] is True


@pytest.mark.asyncio
async def test_sync_reports_no_recent_push_without_raising(monkeypatch):
    import src.integrations.personal.apple_health as provider_module

    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="connected",
    )
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        provider_module, "get_redis", AsyncMock(return_value=fake_redis)
    )

    provider = AppleHealthIntegration()
    db = MagicMock()
    db.commit = AsyncMock()
    result = await provider.sync(integration=integration, db=db)

    assert "no recent data" in result.summary
