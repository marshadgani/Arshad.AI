"""Tests for the OpenWeatherMap HTTP transport and provider (FEAT-138).

``src/integrations/personal/openweathermap.py`` is the only place that
talks to api.openweathermap.org, and the only place the raw API key ever
reaches an HTTP request. ``test_weather_service.py`` covers the dashboard
decision tree with ``fetch_current_weather``/``resolve_city`` patched out
entirely — it never exercises this module's actual status-code mapping,
JSON parsing, or (most importantly) the API-key-leak guard the module's
own docstring calls out. This file closes that gap.

Mocking pattern follows test_shopify_client.py: monkeypatch
``httpx.AsyncClient`` at the module boundary so no real network call is
made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal import openweathermap as owm
from src.integrations.personal.openweathermap import (
    _DEFAULT_CITY,
    OpenWeatherMapIntegration,
    fetch_current_weather,
    resolve_city,
)

_SECRET_KEY = "super-secret-api-key-should-never-leak"


# ── helpers ──────────────────────────────────────────────────────────────


def _mock_httpx_client(
    response: MagicMock | None = None, *, get: AsyncMock | None = None
):
    mock_client = AsyncMock()
    mock_client.get = get if get is not None else AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _response(status_code: int, body=None, *, raise_json: bool = False) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if raise_json:
        resp.json = MagicMock(side_effect=ValueError("not JSON"))
    else:
        resp.json = MagicMock(return_value=body if body is not None else {})
    return resp


_OWM_BODY = {
    "main": {"temp": 15.0},
    "weather": [{"main": "Clouds"}],
    "name": "London",
}


# ── fetch_current_weather — request construction ──────────────────────────


@pytest.mark.asyncio
async def test_fetch_current_weather_sends_expected_query_params(monkeypatch):
    mock_client = _mock_httpx_client(_response(200, _OWM_BODY))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    result = await fetch_current_weather("my-key", "Berlin,DE")

    assert result == _OWM_BODY
    _, kwargs = mock_client.get.call_args
    assert kwargs["params"] == {"q": "Berlin,DE", "appid": "my-key", "units": "metric"}


@pytest.mark.asyncio
async def test_fetch_current_weather_hits_the_current_weather_endpoint(monkeypatch):
    mock_client = _mock_httpx_client(_response(200, _OWM_BODY))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    await fetch_current_weather("key", "Paris")

    args, _ = mock_client.get.call_args
    assert args[0] == f"{owm._BASE}/weather"


@pytest.mark.asyncio
async def test_fetch_current_weather_non_dict_body_returns_empty_dict(monkeypatch):
    """A 2xx body that parses to a JSON array/scalar (not an object) must not
    propagate as-is — every caller expects a dict it can call .get() on."""
    mock_client = _mock_httpx_client(_response(200, ["not", "a", "dict"]))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    assert await fetch_current_weather("key", "London") == {}


# ── fetch_current_weather — HTTP status mapping ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_fetch_current_weather_auth_errors_map_to_invalid_key(
    monkeypatch, status
):
    mock_client = _mock_httpx_client(_response(status))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather("bad-key", "London")

    assert exc_info.value.code == "invalid_key"


@pytest.mark.asyncio
async def test_fetch_current_weather_429_maps_to_rate_limited(monkeypatch):
    mock_client = _mock_httpx_client(_response(429))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather("key", "London")

    assert exc_info.value.code == "rate_limited"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 500, 503])
async def test_fetch_current_weather_other_4xx_5xx_map_to_upstream_error(
    monkeypatch, status
):
    mock_client = _mock_httpx_client(_response(status))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather("key", "NoSuchCity")

    assert exc_info.value.code == "upstream_error"


@pytest.mark.asyncio
async def test_fetch_current_weather_malformed_json_body_maps_to_upstream_error(
    monkeypatch,
):
    """A 200 with a non-JSON body (proxy error page, truncated transfer)
    must raise IntegrationError, not ValueError, so callers don't need to
    know about JSON decoding at all."""
    mock_client = _mock_httpx_client(_response(200, raise_json=True))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather("key", "London")

    assert exc_info.value.code == "upstream_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "network_exc",
    [httpx.TimeoutException("timed out"), httpx.ConnectError("refused")],
)
async def test_fetch_current_weather_network_failures_map_to_unreachable(
    monkeypatch, network_exc
):
    mock_client = _mock_httpx_client(get=AsyncMock(side_effect=network_exc))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather("key", "London")

    assert exc_info.value.code == "unreachable"


# ── fetch_current_weather — security: API key must never leak ─────────────


@pytest.mark.asyncio
async def test_401_error_message_does_not_contain_the_api_key(monkeypatch):
    mock_client = _mock_httpx_client(_response(401))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather(_SECRET_KEY, "London")

    assert _SECRET_KEY not in str(exc_info.value)
    assert _SECRET_KEY not in exc_info.value.message


@pytest.mark.asyncio
async def test_upstream_error_message_does_not_contain_the_api_key(monkeypatch):
    mock_client = _mock_httpx_client(_response(500))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather(_SECRET_KEY, "London")

    assert _SECRET_KEY not in str(exc_info.value)


@pytest.mark.asyncio
async def test_timeout_error_message_does_not_contain_the_api_key(monkeypatch):
    mock_client = _mock_httpx_client(
        get=AsyncMock(side_effect=httpx.TimeoutException("t"))
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await fetch_current_weather(_SECRET_KEY, "London")

    assert _SECRET_KEY not in str(exc_info.value)


# ── resolve_city ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config, expected",
    [
        ({"city": "Paris,FR"}, "Paris,FR"),
        ({"city": "  Berlin,DE  "}, "Berlin,DE"),
        ({"city": None}, _DEFAULT_CITY),
        ({"city": ""}, _DEFAULT_CITY),
        ({"city": "   "}, _DEFAULT_CITY),
        ({}, _DEFAULT_CITY),
        (None, _DEFAULT_CITY),
    ],
)
def test_resolve_city(config, expected):
    assert resolve_city(config) == expected


# ── connect() ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_probes_with_provided_city_before_storing(monkeypatch):
    provider = OpenWeatherMapIntegration()
    user = MagicMock(id="user-1")
    integration_row = MagicMock()
    integration_row.config = {}
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=integration_row)
    db.commit = AsyncMock()

    probe = AsyncMock(return_value=_OWM_BODY)
    monkeypatch.setattr(owm, "fetch_current_weather", probe)
    monkeypatch.setattr(
        owm, "store_api_key", AsyncMock(return_value=MagicMock(integration_id="int-1"))
    )
    monkeypatch.setattr(owm, "del_cached", AsyncMock())

    await provider.connect(
        user=user, db=db, payload={"api_key": "key-abc", "city": "Paris,FR"}
    )

    probe.assert_awaited_once_with("key-abc", "Paris,FR")
    assert integration_row.config.get("city") == "Paris,FR"


@pytest.mark.asyncio
async def test_connect_defaults_to_london_when_city_omitted(monkeypatch):
    provider = OpenWeatherMapIntegration()
    user = MagicMock(id="user-2")
    integration_row = MagicMock()
    integration_row.config = {}
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=integration_row)
    db.commit = AsyncMock()

    probe = AsyncMock(return_value=_OWM_BODY)
    monkeypatch.setattr(owm, "fetch_current_weather", probe)
    monkeypatch.setattr(
        owm, "store_api_key", AsyncMock(return_value=MagicMock(integration_id="int-2"))
    )
    monkeypatch.setattr(owm, "del_cached", AsyncMock())

    await provider.connect(user=user, db=db, payload={"api_key": "key-abc"})

    probe.assert_awaited_once_with("key-abc", _DEFAULT_CITY)


@pytest.mark.asyncio
async def test_connect_rejects_an_invalid_key_before_storing_anything(monkeypatch):
    """The probe must run BEFORE store_api_key — an invalid key must never
    be persisted as a 'connected' integration."""
    provider = OpenWeatherMapIntegration()
    user = MagicMock(id="user-3")
    db = AsyncMock()

    monkeypatch.setattr(
        owm,
        "fetch_current_weather",
        AsyncMock(side_effect=IntegrationError("invalid_key", "rejected")),
    )
    store = AsyncMock()
    monkeypatch.setattr(owm, "store_api_key", store)

    with pytest.raises(IntegrationError):
        await provider.connect(user=user, db=db, payload={"api_key": "bad-key"})

    store.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_without_api_key_raises_before_any_network_call(monkeypatch):
    provider = OpenWeatherMapIntegration()
    user = MagicMock(id="user-4")
    db = AsyncMock()

    probe = AsyncMock()
    monkeypatch.setattr(owm, "fetch_current_weather", probe)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=user, db=db, payload={})

    assert exc_info.value.code == "missing_api_key"
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_invalidates_the_dashboard_cache(monkeypatch):
    """A reconnect with a new city must drop the cached tile — otherwise
    the dashboard serves the old city until the TTL lapses (same
    integration id is reused by store_api_key's upsert)."""
    provider = OpenWeatherMapIntegration()
    user = MagicMock(id="user-5")
    integration_row = MagicMock()
    integration_row.config = {}
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=integration_row)
    db.commit = AsyncMock()

    monkeypatch.setattr(owm, "fetch_current_weather", AsyncMock(return_value=_OWM_BODY))
    monkeypatch.setattr(
        owm, "store_api_key", AsyncMock(return_value=MagicMock(integration_id="int-6"))
    )
    del_cached = AsyncMock()
    monkeypatch.setattr(owm, "del_cached", del_cached)

    await provider.connect(user=user, db=db, payload={"api_key": "key", "city": "Rome"})

    del_cached.assert_awaited_once_with("int-6")


# ── sync() — DEFECT-B regression guard ─────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_merges_config_and_does_not_wipe_the_configured_city(monkeypatch):
    """Regression guard for DEFECT-B: sync() previously replaced
    integration.config wholesale, silently dropping the user's configured
    city (and any other key) on every scheduled sync."""
    provider = OpenWeatherMapIntegration()
    integration = MagicMock()
    integration.id = "int-sync-1"
    integration.config = {"city": "Berlin,DE", "verified_with_city": "Berlin,DE"}

    creds = MagicMock()
    creds.encrypted_key = b"blob"
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=creds)
    db.commit = AsyncMock()

    monkeypatch.setattr(owm, "decrypt", lambda _: "real-key")
    monkeypatch.setattr(
        owm,
        "fetch_current_weather",
        AsyncMock(return_value={"main": {"temp": 10.0}, "weather": [{"main": "Rain"}]}),
    )
    monkeypatch.setattr(owm, "mark_synced", AsyncMock(return_value=MagicMock(ok=True)))
    monkeypatch.setattr(owm, "del_cached", AsyncMock())

    await provider.sync(integration=integration, db=db)

    assert integration.config["city"] == "Berlin,DE"
    assert integration.config["verified_with_city"] == "Berlin,DE"


@pytest.mark.asyncio
async def test_sync_preserves_unknown_config_keys(monkeypatch):
    provider = OpenWeatherMapIntegration()
    integration = MagicMock()
    integration.id = "int-sync-2"
    integration.config = {"city": "Tokyo,JP", "some_future_key": "preserve-me"}

    creds = MagicMock()
    creds.encrypted_key = b"blob"
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=creds)
    db.commit = AsyncMock()

    monkeypatch.setattr(owm, "decrypt", lambda _: "key")
    monkeypatch.setattr(
        owm,
        "fetch_current_weather",
        AsyncMock(
            return_value={"main": {"temp": 20.0}, "weather": [{"main": "Clear"}]}
        ),
    )
    monkeypatch.setattr(owm, "mark_synced", AsyncMock(return_value=MagicMock(ok=True)))
    monkeypatch.setattr(owm, "del_cached", AsyncMock())

    await provider.sync(integration=integration, db=db)

    assert integration.config["some_future_key"] == "preserve-me"


@pytest.mark.asyncio
async def test_sync_without_stored_credential_raises_not_connected(monkeypatch):
    provider = OpenWeatherMapIntegration()
    integration = MagicMock()
    integration.id = "int-sync-3"
    integration.config = {}
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.sync(integration=integration, db=db)

    assert exc_info.value.code == "not_connected"


@pytest.mark.asyncio
async def test_sync_marks_error_and_reraises_on_upstream_failure(monkeypatch):
    provider = OpenWeatherMapIntegration()
    integration = MagicMock()
    integration.id = "int-sync-4"
    integration.config = {"city": "Oslo"}

    creds = MagicMock()
    creds.encrypted_key = b"blob"
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=creds)
    db.commit = AsyncMock()

    monkeypatch.setattr(owm, "decrypt", lambda _: "key")
    monkeypatch.setattr(
        owm,
        "fetch_current_weather",
        AsyncMock(side_effect=IntegrationError("upstream_error", "HTTP 503")),
    )
    mark_error = AsyncMock()
    monkeypatch.setattr(owm, "mark_error", mark_error)

    with pytest.raises(IntegrationError):
        await provider.sync(integration=integration, db=db)

    mark_error.assert_awaited_once()


# ── connect_prompt ───────────────────────────────────────────────────────


def test_connect_prompt_shape():
    prompt = OpenWeatherMapIntegration.connect_prompt
    assert prompt["field"] == "city"
    assert "label" in prompt
    assert "placeholder" in prompt


# ── SEC: city length cap at the trust boundary ───────────────────────────


def test_resolve_city_rejects_overlong_city():
    """An over-long city never reaches the outbound query string — it falls
    back to the default instead of being persisted and replayed on every
    dashboard render."""
    assert resolve_city({"city": "A" * (owm._MAX_CITY_LEN + 1)}) == _DEFAULT_CITY


def test_resolve_city_accepts_city_at_the_cap():
    city = "A" * owm._MAX_CITY_LEN
    assert resolve_city({"city": city}) == city


@pytest.mark.asyncio
async def test_connect_rejects_overlong_city():
    """connect() tells the user rather than silently substituting the
    default — and rejects before the key is stored or any egress happens."""
    with pytest.raises(IntegrationError) as exc_info:
        await OpenWeatherMapIntegration().connect(
            user=MagicMock(),
            db=MagicMock(),
            payload={
                "api_key": _SECRET_KEY,
                "city": "A" * (owm._MAX_CITY_LEN + 1),
            },
        )
    assert exc_info.value.code == "invalid_city"
