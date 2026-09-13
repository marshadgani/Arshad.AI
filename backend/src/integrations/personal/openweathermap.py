"""OpenWeatherMap — query-param auth, doesn't fit the bulk factory."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, ClassVar

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import decrypt
from ...models.integration import ApiKeyCredential, Integration
from ...models.user import User
from ...services.weather.cache import del_cached
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from ..project._shared import (
    mark_error,
    mark_synced,
    project_status,
    require_api_key,
    store_api_key,
)
from ..registry import register

_BASE = "https://api.openweathermap.org/data/2.5"
_DEFAULT_CITY = "London"
# OpenWeatherMap's longest real "City,ST,CC" query is well under this. The
# value arrives on an untyped `dict[str, Any]` connect payload
# (integrations/routers.py:connect_integration), is persisted verbatim into
# integration.config JSONB and replayed into an outbound query string on
# every dashboard render, so it is capped at the boundary rather than
# trusted for being "just a city name".
_MAX_CITY_LEN = 80
_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


async def fetch_current_weather(api_key: str, city: str) -> dict[str, Any]:
    """The single egress point for talking to api.openweathermap.org.

    Used by connect()'s probe, sync(), and services/weather/service.py so
    timeout policy, unit system, and error sanitisation live in exactly one
    place.

    Every httpx.HTTPError is caught and re-raised as a sanitised
    IntegrationError carrying only the exception class name / HTTP status
    code — NEVER the request URL, params, or response body. The upstream
    URL includes ``appid={api_key}`` in its query string; letting the raw
    exception (or its ``str()``) propagate would leak the key into
    ``integration.last_error``, which the integrations status endpoint
    surfaces to the browser, and into application logs.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BASE}/weather",
                params={"q": city, "appid": api_key, "units": "metric"},
            )
        if resp.status_code in (401, 403):
            raise IntegrationError(
                "invalid_key",
                "OpenWeatherMap rejected the API key "
                "(free keys take ~10 min to activate).",
            )
        if resp.status_code == 429:
            raise IntegrationError("rate_limited", "OpenWeatherMap rate limit reached.")
        if resp.status_code >= 400:
            raise IntegrationError(
                "upstream_error",
                f"OpenWeatherMap returned HTTP {resp.status_code}.",
            )
        try:
            body = resp.json()
        except ValueError as exc:
            # A 2xx response with a non-JSON or empty body (redirect,
            # upstream proxy error page, truncated transfer, ...) must not
            # escape as a raw exception — every caller of this function
            # (connect()'s probe, sync(), services/weather/service.py) only knows
            # how to handle IntegrationError.
            raise IntegrationError(
                "upstream_error",
                "OpenWeatherMap returned an unparseable response "
                f"({type(exc).__name__}).",
            ) from exc
        return body if isinstance(body, dict) else {}
    except IntegrationError:
        raise
    except httpx.HTTPError as exc:
        raise IntegrationError(
            "unreachable", f"OpenWeatherMap unreachable ({type(exc).__name__})."
        ) from exc


def resolve_city(source: Mapping[str, Any] | None) -> str:
    """Which city this integration asks OpenWeatherMap about.

    One rule, three readers: the connect payload, ``integration.config`` on
    sync, and ``services/weather/service.py`` on every dashboard render.
    Previously each restated it — and the service kept its own copy of
    ``_DEFAULT_CITY`` — so a change to the default or to the
    blank-input rule silently applied to some paths and not others.

    Anything that is not a non-blank string (absent, ``None``, whitespace)
    falls back to the default rather than reaching the query string, where
    httpx would drop a ``None`` ``q`` and turn it into an upstream 400.
    Over-long values fall back too — see ``_MAX_CITY_LEN``; ``connect()``
    rejects them outright so the user is told, rather than silently served
    London.
    """
    city = (source or {}).get("city")
    if not isinstance(city, str):
        return _DEFAULT_CITY
    stripped = city.strip()
    if not stripped or len(stripped) > _MAX_CITY_LEN:
        return _DEFAULT_CITY
    return stripped


@register
class OpenWeatherMapIntegration(IntegrationProvider):
    slug = "openweathermap"
    kind = "personal_apikey"
    display_name = "OpenWeatherMap"
    category = "Lifestyle"
    description = "Current weather and 5-day forecasts via API key."
    docs_url = "https://openweathermap.org/api"
    icon = "weather"
    connect_prompt: ClassVar[dict[str, str]] = {
        "field": "city",
        "label": "City",
        "placeholder": "London,GB",
    }

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        api_key = require_api_key(payload)
        raw_city = (payload or {}).get("city")
        if isinstance(raw_city, str) and len(raw_city.strip()) > _MAX_CITY_LEN:
            raise IntegrationError(
                "invalid_city",
                f"City must be at most {_MAX_CITY_LEN} characters.",
            )
        city = resolve_city(payload)
        await fetch_current_weather(api_key, city)
        result = await store_api_key(
            db=db,
            slug=self.slug,
            api_key=api_key,
            extra={"verified_with_city": city},
            scopes=["weather:read"],
            user_id=user.id,
            kind="personal_apikey",
        )
        integration = await db.scalar(
            select(Integration).where(Integration.id == result.integration_id)
        )
        if integration is not None:
            integration.config = {**(integration.config or {}), "city": city}
            await db.commit()
        # store_api_key() upserts the SAME integration row (and id) on a
        # reconnect, so the dashboard's cached tile is keyed identically
        # before and after a city change. Drop it or the widget serves the
        # previous city until the TTL lapses.
        await del_cached(str(result.integration_id))
        return result

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError("not_connected", "OpenWeatherMap key not stored.")
        api_key = decrypt(creds.encrypted_key)
        # Sync grabs current weather for the user's configured city (default London).
        city = resolve_city(integration.config)
        # End the read-only transaction opened by the creds SELECT above
        # before the outbound HTTP call below — otherwise a DB connection
        # sits idle-in-transaction for the duration of the OpenWeatherMap
        # request (up to the 5s timeout). mark_error()/mark_synced() each
        # open their own transaction afterward, so this doesn't change
        # write semantics.
        await db.commit()
        try:
            body = await fetch_current_weather(api_key, city)
        except IntegrationError as exc:
            await mark_error(integration=integration, db=db, err=exc)
            raise
        # Merge, never replace — a wholesale reassignment here would drop
        # verified_with_city (or any future config key) on every sync.
        # JSONB is not change-tracked on in-place mutation, so the merged
        # dict is reassigned wholesale rather than mutated key-by-key.
        integration.config = {
            **(integration.config or {}),
            "city": city,
            "last_temperature_c": (body.get("main") or {}).get("temp"),
            "last_conditions": [w.get("main") for w in (body.get("weather") or [])],
        }
        synced = await mark_synced(
            integration=integration,
            db=db,
            summary=f"OpenWeatherMap: {city} weather refreshed.",
            started=started,
        )
        # A manual Sync is the user asking for fresh conditions; leaving the
        # dashboard's cached tile in place would make the button a no-op for
        # up to the cache TTL.
        await del_cached(str(integration.id))
        return synced

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
