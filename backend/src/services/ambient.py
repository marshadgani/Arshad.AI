"""Live weather and news for the dashboard's ambient card.

Both sources are free and keyless (Open-Meteo, Hacker News Firebase API).
Failures raise ``AmbientUnavailable`` so callers can show an honest empty
state instead of fabricated values.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

_HN = "https://hacker-news.firebaseio.com/v0"
_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
_NEWS_TTL_SECONDS = 600
_NEWS_COUNT = 5

_news_cache: tuple[float, list[dict[str, str]]] | None = None

# WMO weather interpretation codes, grouped.
_CONDITIONS = {
    0: "Clear sky",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


class AmbientUnavailable(Exception):
    """The upstream feed could not be reached or returned unusable data."""


def condition_label(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _CONDITIONS.get(code, "Unknown")


async def fetch_weather(latitude: float, longitude: float, city: str) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                _OPEN_METEO,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,weather_code",
                },
            )
            resp.raise_for_status()
            body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AmbientUnavailable(f"open-meteo: {type(exc).__name__}") from exc

    current = body.get("current") if isinstance(body, dict) else None
    if not isinstance(current, dict):
        raise AmbientUnavailable("open-meteo: unexpected response shape")

    temp = current.get("temperature_2m")
    if not isinstance(temp, (int, float)):
        raise AmbientUnavailable("open-meteo: no numeric temperature in response")
    return {
        "temp": f"{round(temp)} °C",
        "condition": condition_label(current.get("weather_code")),
        "city": city,
    }


async def _fetch_story(
    client: httpx.AsyncClient, story_id: int
) -> dict[str, str] | None:
    resp = await client.get(f"{_HN}/item/{story_id}.json")
    resp.raise_for_status()
    item: Any = resp.json() or {}
    title = item.get("title")
    if not title:
        return None
    return {"id": f"hn-{story_id}", "title": title, "source": "Hacker News"}


async def fetch_news() -> list[dict[str, str]]:
    """Top stories, cached 10 minutes. On upstream failure serve the last good
    list if there is one, otherwise raise AmbientUnavailable."""
    global _news_cache
    now = time.monotonic()
    if _news_cache and now - _news_cache[0] < _NEWS_TTL_SECONDS:
        return _news_cache[1]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            top = await client.get(f"{_HN}/topstories.json")
            top.raise_for_status()
            ids = top.json()
            if not isinstance(ids, list):
                raise ValueError("topstories is not a list")
            results = await asyncio.gather(
                *(_fetch_story(client, i) for i in ids[:_NEWS_COUNT]),
                return_exceptions=True,
            )
    except (httpx.HTTPError, ValueError) as exc:
        if _news_cache:
            return _news_cache[1]
        raise AmbientUnavailable(f"hacker-news: {type(exc).__name__}") from exc

    items = [r for r in results if isinstance(r, dict)]
    if not items:
        if _news_cache:
            return _news_cache[1]
        raise AmbientUnavailable("hacker-news: no stories returned")
    _news_cache = (now, items)
    return items


def reset_news_cache() -> None:
    global _news_cache
    _news_cache = None
