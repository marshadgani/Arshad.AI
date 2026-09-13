"""Tests for OpenWeatherMapIntegration.connect() and .sync().

Both methods were entirely uncovered: existing weather test files only
exercise the dashboard read path (services/weather/service.py) and the raw
HTTP client (fetch_current_weather). connect() and sync() are the two
places that actually wire the widget to a real credential, and both carry
non-trivial behaviour (cache invalidation on city change, config merge
semantics, error-status persistence on sync failure) called out explicitly
in the module's own docstrings/comments — none of which had a test.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.integrations.base import IntegrationError
from backend.src.integrations.personal import openweathermap as owm_module
from backend.src.integrations.personal.openweathermap import OpenWeatherMapIntegration

_OWM_RAW = {
    "main": {"temp": 15.2},
    "weather": [{"main": "Clouds"}],
    "name": "London",
}


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


def _make_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


def _make_integration(config: dict | None = None):
    integration = MagicMock()
    integration.id = uuid.uuid4()
    integration.slug = "openweathermap"
    integration.config = config or {}
    return integration


# ---------------------------------------------------------------------------
# connect() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_validates_key_before_storing():
    """connect() must probe the key against the live API before persisting
    it — a bad key must never be stored as if it were valid."""
    provider = OpenWeatherMapIntegration()
    user = _make_user()
    db = _make_db()
    result = MagicMock()
    result.integration_id = uuid.uuid4()
    integration = _make_integration()

    fetch_mock = AsyncMock(return_value=_OWM_RAW)
    store_mock = AsyncMock(return_value=result)

    with (
        patch.object(owm_module, "fetch_current_weather", fetch_mock),
        patch.object(owm_module, "store_api_key", store_mock),
        patch.object(owm_module, "del_cached", AsyncMock()),
    ):
        db.scalar = AsyncMock(return_value=integration)
        await provider.connect(
            user=user, db=db, payload={"api_key": "valid-key", "city": "London"}
        )

    fetch_mock.assert_awaited_once_with("valid-key", "London")
    store_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_invalid_key_raises_and_does_not_store():
    """If the probe call raises IntegrationError, store_api_key must never
    be called — an unverified key must not be persisted."""
    provider = OpenWeatherMapIntegration()
    user = _make_user()
    db = _make_db()
    store_mock = AsyncMock()

    with (
        patch.object(
            owm_module,
            "fetch_current_weather",
            AsyncMock(side_effect=IntegrationError("invalid_key", "bad key")),
        ),
        patch.object(owm_module, "store_api_key", store_mock),
    ):
        with pytest.raises(IntegrationError):
            await provider.connect(
                user=user, db=db, payload={"api_key": "bad-key", "city": "London"}
            )

    store_mock.assert_not_called()


@pytest.mark.asyncio
async def test_connect_missing_api_key_raises_before_any_http_call():
    """require_api_key() must reject an empty/missing key before the
    network probe is ever attempted."""
    provider = OpenWeatherMapIntegration()
    user = _make_user()
    db = _make_db()
    fetch_mock = AsyncMock()

    with patch.object(owm_module, "fetch_current_weather", fetch_mock):
        with pytest.raises(IntegrationError) as exc_info:
            await provider.connect(user=user, db=db, payload={"city": "London"})

    assert exc_info.value.code == "missing_api_key"
    fetch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_connect_requires_user_context():
    provider = OpenWeatherMapIntegration()
    db = _make_db()
    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=None, db=db, payload={"api_key": "k"})
    assert exc_info.value.code == "auth_required"


@pytest.mark.asyncio
async def test_connect_stores_city_in_integration_config():
    """The connect-time city must land in integration.config['city'] — this
    is what services/weather/service.py's resolve_city() reads on every
    dashboard render."""
    provider = OpenWeatherMapIntegration()
    user = _make_user()
    db = _make_db()
    result = MagicMock()
    result.integration_id = uuid.uuid4()
    integration = _make_integration(config={"verified_with_city": "Tokyo"})
    db.scalar = AsyncMock(return_value=integration)

    with (
        patch.object(
            owm_module, "fetch_current_weather", AsyncMock(return_value=_OWM_RAW)
        ),
        patch.object(owm_module, "store_api_key", AsyncMock(return_value=result)),
        patch.object(owm_module, "del_cached", AsyncMock()),
    ):
        await provider.connect(
            user=user, db=db, payload={"api_key": "key", "city": "Tokyo"}
        )

    assert integration.config["city"] == "Tokyo"
    # Merge, not replace — pre-existing config keys must survive.
    assert integration.config["verified_with_city"] == "Tokyo"


@pytest.mark.asyncio
async def test_connect_invalidates_cache_on_reconnect():
    """Regression guard for the documented city-change bug: connect() must
    call del_cached(integration_id) so a reconnect with a different city is
    not masked by the old city's cached tile for up to CACHE_TTL_SECONDS."""
    provider = OpenWeatherMapIntegration()
    user = _make_user()
    db = _make_db()
    integration_id = uuid.uuid4()
    result = MagicMock()
    result.integration_id = integration_id
    integration = _make_integration()
    db.scalar = AsyncMock(return_value=integration)
    del_cached_mock = AsyncMock()

    with (
        patch.object(
            owm_module, "fetch_current_weather", AsyncMock(return_value=_OWM_RAW)
        ),
        patch.object(owm_module, "store_api_key", AsyncMock(return_value=result)),
        patch.object(owm_module, "del_cached", del_cached_mock),
    ):
        await provider.connect(
            user=user, db=db, payload={"api_key": "key", "city": "Berlin"}
        )

    del_cached_mock.assert_awaited_once_with(str(integration_id))


@pytest.mark.asyncio
async def test_connect_handles_missing_integration_row_gracefully():
    """If the freshly-stored integration cannot be re-read (edge case), the
    config-merge step must not raise — db.scalar() returning None must be
    tolerated."""
    provider = OpenWeatherMapIntegration()
    user = _make_user()
    db = _make_db()
    result = MagicMock()
    result.integration_id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=None)

    with (
        patch.object(
            owm_module, "fetch_current_weather", AsyncMock(return_value=_OWM_RAW)
        ),
        patch.object(owm_module, "store_api_key", AsyncMock(return_value=result)),
        patch.object(owm_module, "del_cached", AsyncMock()),
    ):
        # Must not raise.
        await provider.connect(
            user=user, db=db, payload={"api_key": "key", "city": "Berlin"}
        )


# ---------------------------------------------------------------------------
# sync() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_updates_config_with_last_conditions():
    provider = OpenWeatherMapIntegration()
    integration = _make_integration(config={"city": "London"})
    db = _make_db()
    creds = MagicMock()
    creds.encrypted_key = "encrypted"
    db.scalar = AsyncMock(return_value=creds)

    with (
        patch.object(owm_module, "decrypt", return_value="plain-key"),
        patch.object(
            owm_module, "fetch_current_weather", AsyncMock(return_value=_OWM_RAW)
        ),
        patch.object(owm_module, "mark_synced", AsyncMock(return_value=MagicMock())),
        patch.object(owm_module, "del_cached", AsyncMock()),
    ):
        await provider.sync(integration=integration, db=db)

    assert integration.config["last_temperature_c"] == 15.2
    assert integration.config["last_conditions"] == ["Clouds"]
    assert integration.config["city"] == "London"


@pytest.mark.asyncio
async def test_sync_merges_config_without_dropping_existing_keys():
    provider = OpenWeatherMapIntegration()
    integration = _make_integration(
        config={"verified_with_city": "London", "city": "London"}
    )
    db = _make_db()
    creds = MagicMock()
    creds.encrypted_key = "encrypted"
    db.scalar = AsyncMock(return_value=creds)

    with (
        patch.object(owm_module, "decrypt", return_value="plain-key"),
        patch.object(
            owm_module, "fetch_current_weather", AsyncMock(return_value=_OWM_RAW)
        ),
        patch.object(owm_module, "mark_synced", AsyncMock(return_value=MagicMock())),
        patch.object(owm_module, "del_cached", AsyncMock()),
    ):
        await provider.sync(integration=integration, db=db)

    assert integration.config["verified_with_city"] == "London"


@pytest.mark.asyncio
async def test_sync_invalidates_cache_so_manual_refresh_is_not_a_no_op():
    provider = OpenWeatherMapIntegration()
    integration = _make_integration(config={"city": "London"})
    db = _make_db()
    creds = MagicMock()
    creds.encrypted_key = "encrypted"
    db.scalar = AsyncMock(return_value=creds)
    del_cached_mock = AsyncMock()

    with (
        patch.object(owm_module, "decrypt", return_value="plain-key"),
        patch.object(
            owm_module, "fetch_current_weather", AsyncMock(return_value=_OWM_RAW)
        ),
        patch.object(owm_module, "mark_synced", AsyncMock(return_value=MagicMock())),
        patch.object(owm_module, "del_cached", del_cached_mock),
    ):
        await provider.sync(integration=integration, db=db)

    del_cached_mock.assert_awaited_once_with(str(integration.id))


# ---------------------------------------------------------------------------
# sync() — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_no_credential_row_raises_not_connected():
    provider = OpenWeatherMapIntegration()
    integration = _make_integration()
    db = _make_db()
    db.scalar = AsyncMock(return_value=None)
    fetch_mock = AsyncMock()

    with patch.object(owm_module, "fetch_current_weather", fetch_mock):
        with pytest.raises(IntegrationError) as exc_info:
            await provider.sync(integration=integration, db=db)

    assert exc_info.value.code == "not_connected"
    fetch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_sync_upstream_failure_calls_mark_error_and_reraises():
    """A sync-time upstream failure must record the error status (so the
    dashboard tile can reflect it) and must still propagate the exception —
    swallowing it here would silently mark a broken sync as 'succeeded'."""
    provider = OpenWeatherMapIntegration()
    integration = _make_integration(config={"city": "London"})
    db = _make_db()
    creds = MagicMock()
    creds.encrypted_key = "encrypted"
    db.scalar = AsyncMock(return_value=creds)
    mark_error_mock = AsyncMock()
    upstream_exc = IntegrationError("rate_limited", "rate limited")

    with (
        patch.object(owm_module, "decrypt", return_value="plain-key"),
        patch.object(
            owm_module, "fetch_current_weather", AsyncMock(side_effect=upstream_exc)
        ),
        patch.object(owm_module, "mark_error", mark_error_mock),
    ):
        with pytest.raises(IntegrationError):
            await provider.sync(integration=integration, db=db)

    mark_error_mock.assert_awaited_once()
    _, kwargs = mark_error_mock.call_args
    assert kwargs["err"] is upstream_exc


@pytest.mark.asyncio
async def test_sync_commits_before_upstream_http_call():
    """The creds SELECT's read-only transaction must be closed (db.commit())
    before the outbound HTTP call, mirroring the same rule enforced on the
    dashboard read path in service.py."""
    provider = OpenWeatherMapIntegration()
    integration = _make_integration(config={"city": "London"})
    db = _make_db()
    creds = MagicMock()
    creds.encrypted_key = "encrypted"
    db.scalar = AsyncMock(return_value=creds)
    call_order: list[str] = []

    async def _commit_spy():
        call_order.append("commit")

    async def _fetch_spy(api_key, city):  # noqa: ARG001
        call_order.append("fetch")
        return _OWM_RAW

    db.commit = _commit_spy

    with (
        patch.object(owm_module, "decrypt", return_value="plain-key"),
        patch.object(owm_module, "fetch_current_weather", _fetch_spy),
        patch.object(owm_module, "mark_synced", AsyncMock(return_value=MagicMock())),
        patch.object(owm_module, "del_cached", AsyncMock()),
    ):
        await provider.sync(integration=integration, db=db)

    assert call_order.index("commit") < call_order.index("fetch")


@pytest.mark.asyncio
async def test_sync_defaults_city_when_config_has_none():
    """sync() must fall back through resolve_city() the same way the
    dashboard read path does — a never-configured integration must sync
    against the default city, not crash on a missing key."""
    provider = OpenWeatherMapIntegration()
    integration = _make_integration(config=None)
    db = _make_db()
    creds = MagicMock()
    creds.encrypted_key = "encrypted"
    db.scalar = AsyncMock(return_value=creds)
    fetch_mock = AsyncMock(return_value=_OWM_RAW)

    with (
        patch.object(owm_module, "decrypt", return_value="plain-key"),
        patch.object(owm_module, "fetch_current_weather", fetch_mock),
        patch.object(owm_module, "mark_synced", AsyncMock(return_value=MagicMock())),
        patch.object(owm_module, "del_cached", AsyncMock()),
    ):
        await provider.sync(integration=integration, db=db)

    fetch_mock.assert_awaited_once_with("plain-key", "London")
