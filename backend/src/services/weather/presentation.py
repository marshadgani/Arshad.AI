"""Tile state -> ``WeatherResponse``. Pure.

The one place that decides what a ``/api/v1/dashboard/weather`` payload
looks like, in each of the four states ``WeatherResponse``'s validator
permits:

  never_connected — OpenWeatherMap has never been connected for this user:
                    the tile with nothing behind it. Renders 'Connect
                    OpenWeatherMap to see live conditions' with an
                    /integrations link on the frontend.
  needs_reauth    — the stored API key is expired, rejected or missing.
  degraded        — the key is fine, upstream failed transiently.
  live            — connected and healthy, with parsed conditions.

Split out of ``service.py`` for the same reason ``shopify/dashboard.py`` is
split out of its router: the orchestrator is left with the decision tree
only, each state's payload is built in exactly one place, and the schema's
state machine stays assertable without a database, a Redis, or a network.
"""

from __future__ import annotations

from ...schemas.dashboard import WeatherResponse
from .conditions import CurrentConditions


def live(conditions: CurrentConditions) -> WeatherResponse:
    """Connected and healthy, carrying the parsed conditions."""
    return WeatherResponse(
        temp=conditions.temp,
        condition=conditions.condition,
        city=conditions.city,
        connected=True,
    )


def needs_reauth() -> WeatherResponse:
    """The stored API key is expired, rejected or missing. Payload fields
    stay ``None`` — the schema's state machine forbids showing stale
    figures next to a "reconnect" prompt."""
    return WeatherResponse(connected=True, needs_reauth=True)


def degraded() -> WeatherResponse:
    """Key is fine, upstream failed transiently."""
    return WeatherResponse(connected=True, degraded=True)


def never_connected() -> WeatherResponse:
    """No OpenWeatherMap integration row for this user — the empty tile.

    A function rather than a module-level constant so no response instance
    is ever aliased across requests, and so all four tile states are reached
    the same way.
    """
    return WeatherResponse(connected=False)
