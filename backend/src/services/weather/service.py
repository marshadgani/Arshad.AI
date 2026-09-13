"""GET /api/v1/dashboard/weather orchestration — live OpenWeatherMap with
graceful degradation, following the Whoop/Shopify graceful-degradation
pattern.

This module owns exactly one thing: the decision tree over (integration
present?, status, cache hit?, credential present?, upstream outcome), and
which tile state each path ends in. Everything it decides *between* is a
sibling module — see the package docstring for that map, plus
``integrations/personal/openweathermap.py`` for the HTTP egress and
``services/integrations/state.py`` for status transitions — so the branch
structure here reads as policy rather than policy interleaved with
mechanism.

Never raises: ``/api/v1/dashboard/weather`` is always HTTP 200, so every
branch — including an unexpected exception, which the entry point catches
— returns a valid ``WeatherResponse`` instead of a 500 on a tile that is
supposed to degrade.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ...integrations.base import IntegrationError
from ...integrations.personal.openweathermap import (
    fetch_current_weather,
    resolve_city,
)
from ...models.integration import Integration
from ..integrations.state import (
    apply_error_status,
    classify_error,
    find_integration,
    mark_healthy,
)
from . import presentation
from .cache import del_cached, get_cached, set_cached
from .conditions import CurrentConditions
from .credentials import load_api_key

if TYPE_CHECKING:
    # Annotation only. Responses are constructed by presentation.py; this
    # module deliberately holds no runtime handle on the schema, so that
    # re-introducing inline construction here is a visible import change.
    from ...schemas.dashboard import WeatherResponse

_log = logging.getLogger(__name__)

_SLUG = "openweathermap"
_REAUTH_CODES = frozenset({"invalid_key"})


async def _fetch_live(
    integration: Integration, api_key: str, city: str, db: AsyncSession
) -> WeatherResponse:
    """One upstream round-trip plus the status transition it implies.

    Called with no transaction open on ``db`` — see the commit in
    ``get_weather_dashboard``.
    """
    try:
        raw = await fetch_current_weather(api_key, city)
    except Exception as exc:  # noqa: BLE001 — classify_error() handles every case
        reauth_required, _ = classify_error(exc, _REAUTH_CODES)
        if not isinstance(exc, IntegrationError):
            # fetch_current_weather() only ever raises IntegrationError, so
            # anything else is a code bug. apply_error_status() records it
            # in integration.last_error only, leaving no application log —
            # hence this line.
            _log.error(
                "Unexpected %s from fetch_current_weather for integration=%s "
                "city=%r — treating as degraded.",
                type(exc).__name__,
                integration.id,
                city,
                exc_info=True,
            )
        await apply_error_status(integration, exc, reauth_required, db)
        if reauth_required:
            return presentation.needs_reauth()
        return presentation.degraded()

    conditions = CurrentConditions.from_upstream(raw)
    await mark_healthy(integration, db)
    await set_cached(str(integration.id), conditions.as_cache_payload())
    return presentation.live(conditions)


async def get_weather_dashboard(
    user_id: uuid.UUID, db: AsyncSession
) -> WeatherResponse:
    """Full weather-fetch flow for the dashboard weather widget. Never
    raises."""
    integration: Integration | None = None
    try:
        integration = await find_integration(str(user_id), _SLUG, db)
        if integration is None:
            return presentation.never_connected()

        if integration.status == "expired":
            return presentation.needs_reauth()

        cached = await get_cached(str(integration.id))
        if cached is not None:
            conditions = CurrentConditions.from_cache(cached)
            if conditions.is_renderable:
                return presentation.live(conditions)
            # Structurally valid JSON that normalises to nothing renderable
            # (wrong value types, or a payload from an older parser shape).
            # Serving it would pin the tile to its unavailable state for the
            # rest of the TTL while a healthy upstream sits one call away, so
            # it is evicted and treated as a miss.
            _log.warning(
                "Weather cache entry for integration=%s has no renderable "
                "conditions — evicting and re-fetching upstream.",
                integration.id,
            )
            await del_cached(str(integration.id))

        api_key = await load_api_key(integration, db)
        if api_key is None:
            return presentation.needs_reauth()

        city = resolve_city(integration.config)

        # Close the read-only transaction opened by the lookups above
        # before the network round-trip, rather than holding a pooled
        # connection idle-in-transaction for the length of an httpx call —
        # see .claude/rules/database.md. mark_healthy()/apply_error_status()
        # each open their own transaction afterward, so write semantics are
        # unchanged.
        await db.commit()

        return await _fetch_live(integration, api_key, city, db)
    except Exception:  # noqa: BLE001
        _log.exception("weather: falling back after an unexpected error")
        try:
            # This handler swallows every exception, so get_db()
            # (models/database.py) never sees one and never rolls back —
            # without this, a dirty connection returns to the pool and
            # poisons the next request that borrows it.
            await db.rollback()
        except Exception:  # noqa: BLE001
            # A second, independent DB failure. Log it: a tile with no
            # trace of why is the worst thing to debug.
            _log.exception("weather: rollback after error also failed")
        # A failure for an already-connected user must degrade, not claim
        # the integration doesn't exist — telling a connected user to
        # reconnect a key they already stored is worse than a stale tile.
        if integration is None:
            return presentation.never_connected()
        return presentation.degraded()
