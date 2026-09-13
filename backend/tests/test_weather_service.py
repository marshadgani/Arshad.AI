"""Tests for the dashboard weather flow (FEAT-138).

``services/weather/service.py`` is a decision tree over (integration
present?, status, cache hit?, credential present?, upstream outcome) that
must never raise — ``/api/v1/dashboard/weather`` is an always-200 endpoint,
so an escaping exception would be a 500 on a tile that is supposed to
degrade. Each branch is asserted here with fakes; no Postgres and no Redis.

``services/weather/conditions.py`` is tested directly as a pure parser,
``services/weather/presentation.py`` as the pure builder of the four tile
states, ``services/weather/credentials.py`` as the stored-key seam, and
``services/weather/cache.py`` for its fail-open contract the same way
``test_shopify_dashboard_cache.py`` tests its Shopify twin.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.exceptions
from pydantic import ValidationError
from src.integrations.base import IntegrationError
from src.schemas.dashboard import WeatherResponse
from src.services.weather import presentation
from src.services.weather import service as svc
from src.services.weather.cache import (
    CACHE_TTL_SECONDS,
    cache_key,
    del_cached,
    get_cached,
    set_cached,
)
from src.services.weather.conditions import CurrentConditions
from src.services.weather.credentials import load_api_key

_USER_ID = uuid.uuid4()
_INTEGRATION_ID = uuid.uuid4()


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_db(seed_row: object | None = None, creds: object | None = None) -> MagicMock:
    """AsyncSession stand-in. execute() backs the seeded fallback SELECT,
    scalar() backs the ApiKeyCredential lookup."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = seed_row
    db.execute = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=creds)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _integration(status: str = "connected", city: str | None = "Tokyo,JP") -> MagicMock:
    integration = MagicMock()
    integration.id = _INTEGRATION_ID
    integration.status = status
    integration.config = {"city": city} if city else {}
    return integration


def _seed_row() -> SimpleNamespace:
    return SimpleNamespace(temp="18 °C", condition="Cloudy", city="London")


_OWM_BODY = {
    "main": {"temp": 21.4},
    "weather": [{"main": "Clouds"}],
    "name": "Tokyo",
}


# ── CurrentConditions ──────────────────────────────────────────────────────


def test_parse_formats_metric_temperature():
    assert CurrentConditions.from_upstream(_OWM_BODY).as_cache_payload() == {
        "temp": "21 °C",
        "condition": "Clouds",
        "city": "Tokyo",
    }


@pytest.mark.parametrize(
    "body",
    [{}, {"main": {}, "weather": []}, {"main": {"temp": None}, "weather": None}],
)
def test_parse_tolerates_missing_fields(body):
    assert CurrentConditions.from_upstream(body) == CurrentConditions()


def test_from_cache_ignores_unknown_keys_and_defaults_missing_ones():
    """A cache entry written by a different parser shape is data, not a
    contract — it must never TypeError the caller."""
    assert CurrentConditions.from_cache({"temp": "9 °C", "extra": 1}) == (
        CurrentConditions(temp="9 °C")
    )


def test_cache_payload_round_trips():
    conditions = CurrentConditions.from_upstream(_OWM_BODY)
    assert CurrentConditions.from_cache(conditions.as_cache_payload()) == conditions


# ── presentation — the four tile states ────────────────────────────────────


def test_live_state_carries_the_parsed_conditions():
    res = presentation.live(
        CurrentConditions(temp="21 °C", condition="Clouds", city="Tokyo")
    )
    assert (res.connected, res.needs_reauth, res.degraded) == (True, False, False)
    assert (res.temp, res.condition, res.city) == ("21 °C", "Clouds", "Tokyo")


def test_needs_reauth_state_hides_stale_figures():
    res = presentation.needs_reauth()
    assert (res.connected, res.needs_reauth, res.degraded) == (True, True, False)
    assert (res.temp, res.condition, res.city) == (None, None, None)


def test_degraded_state_hides_stale_figures():
    res = presentation.degraded()
    assert (res.connected, res.needs_reauth, res.degraded) == (True, False, True)
    assert (res.temp, res.condition, res.city) == (None, None, None)


def test_never_connected_state_is_an_empty_tile():
    res = presentation.never_connected()
    assert res == WeatherResponse(connected=False)


def test_never_connected_returns_a_fresh_response_each_call():
    """No shared module-level response instance: WeatherResponse is mutable,
    so one request must never be able to observe another's mutation."""
    assert presentation.never_connected() is not presentation.never_connected()


# ── credentials ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_api_key_decrypts_the_stored_credential():
    db = _make_db(creds=SimpleNamespace(encrypted_key=b"blob"))
    with patch(
        "src.services.weather.credentials.decrypt", return_value="key-123"
    ) as decrypt_mock:
        assert await load_api_key(_integration(), db) == "key-123"
    decrypt_mock.assert_called_once_with(b"blob")


@pytest.mark.asyncio
async def test_load_api_key_returns_none_when_no_credential_row_exists():
    """An active integration with no stored key is anomalous, but it must
    resolve to a needs_reauth branch rather than raise on an always-200
    endpoint."""
    assert await load_api_key(_integration(), _make_db(creds=None)) is None


# ── get_weather_dashboard — branch coverage ────────────────────────────────


@pytest.mark.asyncio
async def test_no_integration_returns_empty_tile():
    db = _make_db()
    with patch.object(svc, "find_integration", AsyncMock(return_value=None)):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert res == WeatherResponse(connected=False)
    assert res.temp is None


@pytest.mark.asyncio
async def test_no_integration_with_a_seed_row_present_still_returns_empty_tile():
    """A leftover Phase A ``m.Weather`` row must never be surfaced again —
    the seeded fallback is gone; this is the regression guard for that."""
    db = _make_db(seed_row=_seed_row())
    with patch.object(svc, "find_integration", AsyncMock(return_value=None)):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert res == WeatherResponse(connected=False)
    assert res.temp is None


@pytest.mark.asyncio
async def test_expired_integration_reports_needs_reauth_without_calling_upstream():
    db = _make_db()
    fetch = AsyncMock()
    with (
        patch.object(
            svc, "find_integration", AsyncMock(return_value=_integration("expired"))
        ),
        patch.object(svc, "fetch_current_weather", fetch),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert (res.connected, res.needs_reauth, res.degraded) == (True, True, False)
    assert res.temp is None
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_hit_short_circuits_the_upstream_call():
    db = _make_db()
    fetch = AsyncMock()
    cached = {"temp": "21 °C", "condition": "Clouds", "city": "Tokyo"}
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(svc, "get_cached", AsyncMock(return_value=cached)),
        patch.object(svc, "fetch_current_weather", fetch),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert (res.connected, res.temp, res.city) == (True, "21 °C", "Tokyo")
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_hit_with_unexpected_keys_does_not_blank_a_connected_tile():
    """A payload written by an older _parse() must not TypeError the caller
    into the disconnected seed fallback."""
    db = _make_db(seed_row=_seed_row())
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(
            svc, "get_cached", AsyncMock(return_value={"temp": "9 °C", "extra": 1})
        ),
        patch.object(svc, "fetch_current_weather", AsyncMock()),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert res.connected is True
    assert res.temp == "9 °C"
    assert res.city is None


@pytest.mark.asyncio
async def test_missing_credential_reports_needs_reauth():
    db = _make_db(creds=None)
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(svc, "get_cached", AsyncMock(return_value=None)),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert (res.connected, res.needs_reauth) == (True, True)


@pytest.mark.asyncio
async def test_load_api_key_returns_none_when_stored_ciphertext_is_undecryptable():
    """A corrupted ciphertext or a rotated OAUTH_ENCRYPTION_KEY (see
    auth/crypto.py; CLAUDE.md documents key rotation as a known lockout
    cause) raises TokenDecryptError from decrypt() and can never succeed on
    retry — it must resolve to the same needs_reauth branch as a missing
    credential, not escape and get misclassified as transient `degraded`
    by get_weather_dashboard's generic handler further up the call chain."""
    from src.auth.crypto import TokenDecryptError

    db = _make_db(creds=SimpleNamespace(encrypted_key=b"corrupted-blob"))
    with patch(
        "src.services.weather.credentials.decrypt",
        side_effect=TokenDecryptError("bad tag"),
    ):
        assert await load_api_key(_integration(), db) is None


@pytest.mark.asyncio
async def test_undecryptable_stored_key_reports_needs_reauth_not_degraded():
    """End-to-end guard for the same failure through the full dashboard
    flow: it must never fall through to the generic `degraded` tile — that
    state implies "transient, will self-heal", which is never true for a
    key that can't be decrypted, and would leave the user stuck with no
    path forward."""
    db = _make_db(creds=SimpleNamespace(encrypted_key=b"corrupted-blob"))
    fetch = AsyncMock()
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(svc, "get_cached", AsyncMock(return_value=None)),
        patch.object(svc, "load_api_key", AsyncMock(return_value=None)),
        patch.object(svc, "fetch_current_weather", fetch),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert (res.connected, res.needs_reauth, res.degraded) == (True, True, False)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_fetch_uses_configured_city_and_caches_the_payload():
    db = _make_db()
    fetch = AsyncMock(return_value=_OWM_BODY)
    set_mock = AsyncMock()
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(svc, "get_cached", AsyncMock(return_value=None)),
        patch.object(svc, "set_cached", set_mock),
        patch.object(svc, "load_api_key", AsyncMock(return_value="key-123")),
        patch.object(svc, "fetch_current_weather", fetch),
        patch.object(svc, "mark_healthy", AsyncMock()),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    fetch.assert_awaited_once_with("key-123", "Tokyo,JP")
    set_mock.assert_awaited_once_with(
        str(_INTEGRATION_ID), {"temp": "21 °C", "condition": "Clouds", "city": "Tokyo"}
    )
    assert (res.connected, res.temp, res.condition) == (True, "21 °C", "Clouds")
    # The read transaction is closed before the network round-trip.
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_unconfigured_city_defaults_to_london():
    db = _make_db()
    fetch = AsyncMock(return_value=_OWM_BODY)
    with (
        patch.object(
            svc, "find_integration", AsyncMock(return_value=_integration(city=None))
        ),
        patch.object(svc, "get_cached", AsyncMock(return_value=None)),
        patch.object(svc, "set_cached", AsyncMock()),
        patch.object(svc, "load_api_key", AsyncMock(return_value="key-123")),
        patch.object(svc, "fetch_current_weather", fetch),
        patch.object(svc, "mark_healthy", AsyncMock()),
    ):
        await svc.get_weather_dashboard(_USER_ID, db)
    fetch.assert_awaited_once_with("key-123", "London")


@pytest.mark.asyncio
async def test_invalid_key_marks_expired_and_reports_needs_reauth():
    db = _make_db()
    apply = AsyncMock()
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(svc, "get_cached", AsyncMock(return_value=None)),
        patch.object(svc, "load_api_key", AsyncMock(return_value="key-123")),
        patch.object(
            svc,
            "fetch_current_weather",
            AsyncMock(side_effect=IntegrationError("invalid_key", "rejected")),
        ),
        patch.object(svc, "apply_error_status", apply),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert (res.connected, res.needs_reauth, res.degraded) == (True, True, False)
    assert apply.await_args.args[2] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        IntegrationError("unreachable", "down"),
        IntegrationError("rate_limited", "slow down"),
        IntegrationError("upstream_error", "HTTP 503"),
    ],
)
async def test_transient_upstream_failure_degrades_rather_than_reauth(exc):
    db = _make_db()
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(svc, "get_cached", AsyncMock(return_value=None)),
        patch.object(svc, "load_api_key", AsyncMock(return_value="key-123")),
        patch.object(svc, "fetch_current_weather", AsyncMock(side_effect=exc)),
        patch.object(svc, "apply_error_status", AsyncMock()),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert (res.connected, res.degraded, res.needs_reauth) == (True, True, False)
    assert res.temp is None


@pytest.mark.asyncio
async def test_unexpected_exception_before_lookup_rolls_back_and_returns_empty_tile():
    db = _make_db()
    with patch.object(
        svc, "find_integration", AsyncMock(side_effect=RuntimeError("db gone"))
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    db.rollback.assert_awaited_once()
    assert res == WeatherResponse(connected=False)


@pytest.mark.asyncio
async def test_unexpected_exception_after_lookup_reports_degraded_not_disconnected():
    """A failure once we know the user IS connected must degrade the tile,
    never claim the integration doesn't exist — see service.py's except
    branch (Architecture Critic HIGH finding)."""
    db = _make_db()
    with (
        patch.object(svc, "find_integration", AsyncMock(return_value=_integration())),
        patch.object(
            svc, "get_cached", AsyncMock(side_effect=RuntimeError("redis gone"))
        ),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert (res.connected, res.degraded) == (True, True)
    assert res.temp is None


@pytest.mark.asyncio
async def test_rollback_failure_still_returns_a_response():
    db = _make_db()
    db.rollback = AsyncMock(side_effect=RuntimeError("rollback also gone"))
    with patch.object(
        svc, "find_integration", AsyncMock(side_effect=RuntimeError("db gone"))
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)
    assert res == WeatherResponse(connected=False)


# ── Schema state machine ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connected": False, "needs_reauth": True},
        {"connected": False, "degraded": True},
        {"connected": True, "needs_reauth": True, "degraded": True},
        {"connected": True, "needs_reauth": True, "temp": "8 °C"},
        {"connected": True, "degraded": True, "city": "London"},
        {"temp": "18 °C", "condition": "Cloudy", "city": "London"},
    ],
)
def test_illegal_weather_states_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        WeatherResponse(**kwargs)


def test_weather_response_is_frozen():
    """model_config = ConfigDict(frozen=True) exists specifically so the
    state-machine validator, which only runs on construction, cannot be
    bypassed by mutating a field afterward into an illegal combination."""
    res = WeatherResponse(connected=True, temp="15 °C")
    with pytest.raises(ValidationError):
        res.temp = "0 °C"  # type: ignore[misc]


# ── cache fail-open contract ───────────────────────────────────────


def test_cache_ttl_matches_ac6_600_seconds():
    assert CACHE_TTL_SECONDS == 600


@pytest.mark.asyncio
async def test_cache_read_returns_parsed_payload():
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=json.dumps({"temp": "1 °C"}))
    with patch(
        "src.services.weather.cache.get_redis", AsyncMock(return_value=redis_client)
    ):
        assert await get_cached("abc") == {"temp": "1 °C"}
    redis_client.get.assert_awaited_once_with(cache_key("abc"))


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["not json", json.dumps([1, 2]), json.dumps("str"), ""])
async def test_cache_read_discards_unusable_payloads(raw):
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=raw)
    with patch(
        "src.services.weather.cache.get_redis", AsyncMock(return_value=redis_client)
    ):
        assert await get_cached("abc") is None


@pytest.mark.asyncio
async def test_cache_helpers_degrade_when_redis_is_unreachable():
    boom = AsyncMock(side_effect=redis.exceptions.ConnectionError("no redis"))
    with patch("src.services.weather.cache.get_redis", boom):
        assert await get_cached("abc") is None
        # Neither write path may raise — the tile must still render.
        await set_cached("abc", {"temp": "1 °C"})
        await del_cached("abc")


@pytest.mark.asyncio
async def test_del_cached_deletes_the_integration_key():
    redis_client = MagicMock()
    redis_client.delete = AsyncMock()
    with patch(
        "src.services.weather.cache.get_redis", AsyncMock(return_value=redis_client)
    ):
        await del_cached("abc")
    redis_client.delete.assert_awaited_once_with(cache_key("abc"))


# ── Regression — an unrenderable cache entry is evicted, not served ────────
#
# A structurally valid JSON object that normalises to no temperature renders
# identically to a degraded tile. Serving it pinned the widget to that state
# for the rest of the 600s TTL while a healthy upstream sat one call away,
# because nothing on the cache-hit path evicted it.


@pytest.mark.asyncio
async def test_unrenderable_cache_entry_is_evicted_and_refetched():
    """Valid JSON, wrong value type for temp: must be dropped and treated as
    a miss rather than served for the rest of the TTL."""
    db = _make_db()
    del_cached_mock = AsyncMock()
    fetch = AsyncMock(return_value=_OWM_BODY)
    with (
        patch.object(
            svc, "find_integration", AsyncMock(return_value=_integration())
        ),
        patch.object(
            svc,
            "get_cached",
            AsyncMock(return_value={"temp": 21.4, "condition": "Clouds"}),
        ),
        patch.object(svc, "del_cached", del_cached_mock),
        patch.object(svc, "load_api_key", AsyncMock(return_value="key")),
        patch.object(svc, "fetch_current_weather", fetch),
        patch.object(svc, "mark_healthy", AsyncMock()),
        patch.object(svc, "set_cached", AsyncMock()),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)

    del_cached_mock.assert_awaited_once_with(str(_INTEGRATION_ID))
    fetch.assert_awaited_once()
    assert (res.connected, res.degraded) == (True, False)
    assert res.temp == "21 \u00b0C"


@pytest.mark.asyncio
async def test_renderable_cache_entry_is_neither_evicted_nor_refetched():
    """The eviction branch must not fire on a healthy hit."""
    db = _make_db()
    del_cached_mock = AsyncMock()
    fetch = AsyncMock()
    with (
        patch.object(
            svc, "find_integration", AsyncMock(return_value=_integration())
        ),
        patch.object(
            svc,
            "get_cached",
            AsyncMock(return_value={"temp": "12 \u00b0C", "condition": "Clear"}),
        ),
        patch.object(svc, "del_cached", del_cached_mock),
        patch.object(svc, "fetch_current_weather", fetch),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)

    del_cached_mock.assert_not_called()
    fetch.assert_not_called()
    assert res.temp == "12 \u00b0C"


@pytest.mark.asyncio
async def test_malformed_upstream_body_parses_per_field_without_raising():
    """``weather: ["Clouds"]`` used to raise AttributeError out of
    from_upstream — which sits *outside* _fetch_live's except — so the tile
    degraded via the outer handler with no reason recorded in
    integration.last_error and mark_healthy() never run, despite upstream
    having answered 200."""
    db = _make_db()
    mark_healthy = AsyncMock()
    with (
        patch.object(
            svc, "find_integration", AsyncMock(return_value=_integration())
        ),
        patch.object(svc, "get_cached", AsyncMock(return_value=None)),
        patch.object(svc, "load_api_key", AsyncMock(return_value="key")),
        patch.object(
            svc,
            "fetch_current_weather",
            AsyncMock(
                return_value={
                    "main": {"temp": 21.4},
                    "weather": ["Clouds"],
                    "name": "Tokyo",
                }
            ),
        ),
        patch.object(svc, "mark_healthy", mark_healthy),
        patch.object(svc, "set_cached", AsyncMock()),
    ):
        res = await svc.get_weather_dashboard(_USER_ID, db)

    mark_healthy.assert_awaited_once()
    assert (res.connected, res.degraded) == (True, False)
    assert res.temp == "21 \u00b0C"
    assert res.condition is None
