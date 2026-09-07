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
    _, ttl = next(v for k, v in fake_redis.store.items() if "snapshot" in k)
    assert ttl is not None and ttl > 0
    assert integration.last_synced_at is not None


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
