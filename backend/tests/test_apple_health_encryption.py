"""Apple Health at-rest encryption envelope and ingest write-failure paths.

Two things are verified here that nothing else covered.

1. The envelope codec (services/apple_health/envelope.py) in isolation:
   every unusable stored value — wrong prefix, bad base64, a flipped GCM
   tag (what a rotated OAUTH_ENCRYPTION_KEY looks like from the reader's
   side), or a payload that no longer matches the schema — must collapse
   to None rather than raise, because the dashboard has exactly one
   cache-miss branch to render.

2. The ingest endpoint's two write-failure exits. Both were unreachable
   by any existing test, and both share one load-bearing invariant: when
   the snapshot was NOT stored, the integration must not be marked freshly
   synced. Reporting a push that never landed would make the dashboard
   claim live data it does not have.

The conftest OAUTH_ENCRYPTION_KEY is a deterministic test constant; the
first test asserts it is recognisably one so a real key can never be used
here by accident.
"""

from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.exceptions
from fastapi.testclient import TestClient
from src.api.v1 import apple_health as apple_health_router_module
from src.auth.crypto import encrypt
from src.auth.dependencies import get_current_user
from src.integrations.personal.apple_health import hash_ingest_token
from src.main import app
from src.models.database import get_db
from src.models.integration import Integration, IntegrationIngestToken
from src.schemas.apple_health import AppleHealthSnapshot
from src.services.apple_health import envelope, snapshot_store
from src.services.apple_health.envelope import (
    SNAPSHOT_ENVELOPE_PREFIX,
    decode_snapshot,
    encode_snapshot,
)

USER_ID = uuid.uuid4()


class _FakeUser:
    id = USER_ID


class _FakeRedis:
    """In-memory stand-in for the async redis client, with an injectable
    failure so the endpoint's RedisError branch is reachable."""

    def __init__(self, fail_on_set: Exception | None = None):
        self.store: dict[str, tuple[str, int | None]] = {}
        self._fail_on_set = fail_on_set

    async def get(self, key):
        entry = self.store.get(key)
        return entry[0] if entry else None

    async def set(self, key, value, ex=None):
        if self._fail_on_set is not None:
            raise self._fail_on_set
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


def _snapshot(**overrides) -> AppleHealthSnapshot:
    base = {
        "connected": True,
        "resting_heart_rate": 65.0,
        "heart_rate_variability_ms": 38.0,
        "sleep_hours": 8.0,
        "active_energy_kcal": 500.0,
        "steps": 12_000,
        "vo2_max": 42.5,
        "recorded_at": datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc),
        "received_at": datetime(2024, 6, 15, 12, 30, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return AppleHealthSnapshot(**base)


# ── Test-key sanity ──────────────────────────────────────────────────────


def test_encryption_key_in_tests_is_clearly_a_test_constant():
    decoded = base64.urlsafe_b64decode(os.environ["OAUTH_ENCRYPTION_KEY"])
    assert b"test" in decoded
    assert len(decoded) == 32


# ── Envelope: seal ───────────────────────────────────────────────────────


def test_encode_writes_the_versioned_envelope_prefix():
    assert encode_snapshot(_snapshot()).startswith(SNAPSHOT_ENVELOPE_PREFIX)


def test_encode_is_ascii_safe_for_a_decode_responses_redis_client():
    """The shared Redis singleton uses decode_responses=True, so the stored
    value must survive as a str — raw AES-GCM bytes would not."""
    encode_snapshot(_snapshot()).encode("ascii")


def test_encoded_value_leaks_no_biometric_field_name():
    encoded = encode_snapshot(_snapshot())
    for field in (
        "resting_heart_rate",
        "heart_rate_variability_ms",
        "sleep_hours",
        "active_energy_kcal",
        "steps",
        "vo2_max",
    ):
        assert field not in encoded


def test_encoding_the_same_snapshot_twice_yields_different_ciphertext():
    """AES-GCM must use a fresh nonce per seal; identical output would mean
    a fixed nonce, which leaks plaintext equality across pushes."""
    snapshot = _snapshot()
    assert encode_snapshot(snapshot) != encode_snapshot(snapshot)


# ── Envelope: unseal ─────────────────────────────────────────────────────


def test_round_trip_preserves_every_field():
    original = _snapshot()
    decoded = decode_snapshot(encode_snapshot(original))
    assert decoded is not None
    assert decoded.model_dump() == original.model_dump()


def test_decode_rejects_a_legacy_cleartext_value():
    """A pre-encryption value left over from a rolling deploy must read as
    a cache miss, not be served as if it were a valid snapshot."""
    assert decode_snapshot('{"connected": true, "resting_heart_rate": 60}') is None


def test_decode_rejects_invalid_base64():
    assert decode_snapshot(SNAPSHOT_ENVELOPE_PREFIX + "!!!not-base64!!!") is None


def test_decode_rejects_ciphertext_with_a_broken_gcm_tag():
    """What a rotated OAUTH_ENCRYPTION_KEY looks like to the reader."""
    corrupted = bytearray(encrypt('{"connected": true}'))
    corrupted[-1] ^= 0xFF
    encoded = SNAPSHOT_ENVELOPE_PREFIX + base64.b64encode(bytes(corrupted)).decode(
        "ascii"
    )
    assert decode_snapshot(encoded) is None


def test_decode_rejects_a_payload_that_no_longer_matches_the_schema():
    """Decrypts cleanly under the current key but fails validation — must
    still be a cache miss rather than a 500."""
    encoded = SNAPSHOT_ENVELOPE_PREFIX + base64.b64encode(
        encrypt('{"not_a_field": true}')
    ).decode("ascii")
    assert decode_snapshot(encoded) is None


def test_decode_rejects_an_empty_envelope_body():
    assert decode_snapshot(SNAPSHOT_ENVELOPE_PREFIX) is None


# ── Ingest endpoint: write-failure exits ─────────────────────────────────


@pytest.fixture
def client():
    async def _override_user():
        return _FakeUser()

    app.dependency_overrides[get_current_user] = _override_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_integration_and_token():
    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="connected",
        config={},
    )
    token = "a-real-shortcut-token"
    token_row = IntegrationIngestToken(
        integration_id=integration.id, token_hash=hash_ingest_token(token)
    )
    return integration, token_row, token


def _wire_db(integration, token_row):
    async def _override_db():
        db = MagicMock()
        db.scalar = AsyncMock(side_effect=[token_row, integration])
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _override_db


def test_ingest_returns_500_when_encryption_is_unavailable(client, monkeypatch):
    """OAUTH_ENCRYPTION_KEY unset/malformed makes encrypt() raise
    RuntimeError. That must surface as an explicit 500 rather than being
    swallowed into a success response — a silently unencrypted or
    unrecorded push is exactly what the hard constraint forbids."""
    integration, token_row, token = _make_integration_and_token()
    _wire_db(integration, token_row)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=fake_redis)
    )
    monkeypatch.setattr(
        envelope,
        "encrypt",
        MagicMock(side_effect=RuntimeError("OAUTH_ENCRYPTION_KEY is not set")),
    )

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 72.0, "sleep_hours": 8.5},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "encryption_unavailable"
    # Nothing stored, and the push must not be reported as a successful sync.
    assert fake_redis.store == {}
    assert integration.last_synced_at is None


def test_encryption_failure_does_not_echo_biometric_values(client, monkeypatch):
    """The error response is rendered to a Shortcut log the user may share;
    it must carry no reading and no field name."""
    integration, token_row, token = _make_integration_and_token()
    _wire_db(integration, token_row)

    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=_FakeRedis())
    )
    monkeypatch.setattr(
        envelope, "encrypt", MagicMock(side_effect=RuntimeError("no key"))
    )

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 72.0, "sleep_hours": 8.5},
        headers={"Authorization": f"Bearer {token}"},
    )

    body = resp.text
    assert "72.0" not in body
    assert "8.5" not in body
    assert "resting_heart_rate" not in body
    # The underlying exception text must not leak either.
    assert "no key" not in body


def test_ingest_returns_503_when_redis_is_unreachable(client, monkeypatch):
    """Distinct from the 500: 'we could not store' and 'we could not
    encrypt' have different fixes, so they must stay distinguishable."""
    integration, token_row, token = _make_integration_and_token()
    _wire_db(integration, token_row)

    fake_redis = _FakeRedis(
        fail_on_set=redis.exceptions.ConnectionError("redis is down")
    )
    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=fake_redis)
    )

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 55.0},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "cache_unavailable"
    # The load-bearing invariant: an unstored push is not a completed sync.
    assert integration.last_synced_at is None


def test_successful_ingest_does_mark_the_integration_synced(client, monkeypatch):
    """Control for the two failure tests above — proves last_synced_at
    staying None there is caused by the failure, not by the fixture."""
    integration, token_row, token = _make_integration_and_token()
    _wire_db(integration, token_row)

    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=_FakeRedis())
    )

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 55.0},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert integration.last_synced_at is not None
    assert integration.status == "connected"
    assert integration.last_error is None


def test_ingest_reports_dropped_fields_back_to_the_shortcut(client, monkeypatch):
    """End-to-end path for the plausibility clamp: the push still succeeds,
    the good metric is stored, and the user can tell which reading was
    discarded without server-log access."""
    integration, token_row, token = _make_integration_and_token()
    _wire_db(integration, token_row)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        apple_health_router_module, "get_redis", AsyncMock(return_value=fake_redis)
    )

    resp = client.post(
        "/api/v1/apple-health/ingest",
        json={"resting_heart_rate": 9999.0, "sleep_hours": 7.5},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["dropped_fields"] == ["resting_heart_rate"]

    stored, _ttl = next(v for k, v in fake_redis.store.items() if "snapshot" in k)
    decoded = decode_snapshot(stored)
    assert decoded is not None
    assert decoded.resting_heart_rate is None
    assert decoded.sleep_hours == 7.5


# ── Store-level read policy ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_absorbs_a_redis_outage_as_a_cache_miss():
    """The always-visible dashboard must never gain a sixth failure branch."""

    class _Down(_FakeRedis):
        async def get(self, key):
            raise redis.exceptions.ConnectionError("redis is down")

    assert await snapshot_store.load(_Down(), str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_has_snapshot_lets_a_redis_outage_propagate():
    """Its caller owns the 'treat an outage as no recent push' decision;
    hard-coding it in the store would move provider policy into storage."""

    class _Down(_FakeRedis):
        async def get(self, key):
            raise redis.exceptions.ConnectionError("redis is down")

    with pytest.raises(redis.exceptions.RedisError):
        await snapshot_store.has_snapshot(_Down(), str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_has_snapshot_is_true_for_an_undecryptable_value():
    """Freshness is proven by the key existing: a post-rotation snapshot is
    unreadable but still evidence the Shortcut ran."""
    redis_client = _FakeRedis()
    integration_id = str(uuid.uuid4())
    await redis_client.set(
        snapshot_store.snapshot_cache_key(integration_id),
        SNAPSHOT_ENVELOPE_PREFIX + "bm90LXJlYWxseS1jaXBoZXJ0ZXh0",
    )

    assert await snapshot_store.has_snapshot(redis_client, integration_id) is True
    assert await snapshot_store.load(redis_client, integration_id) is None


@pytest.mark.asyncio
async def test_write_seals_under_the_ttl():
    redis_client = _FakeRedis()
    integration_id = str(uuid.uuid4())
    await snapshot_store.write(redis_client, integration_id, _snapshot())

    stored, ttl = redis_client.store[snapshot_store.snapshot_cache_key(integration_id)]
    assert ttl == snapshot_store.CACHE_TTL_SECONDS
    assert stored.startswith(SNAPSHOT_ENVELOPE_PREFIX)
