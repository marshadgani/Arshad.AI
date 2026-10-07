"""Weather and news come from live keyless APIs; failures are never faked."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from src.api.v1 import dashboard
from src.services import ambient


def _patch_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(ambient.httpx, "AsyncClient", factory)


class FakeDB:
    def __init__(self, integration):
        self._integration = integration

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self._integration)


USER = SimpleNamespace(id="u1")


@pytest.fixture(autouse=True)
def _clear_cache():
    ambient.reset_news_cache()
    yield
    ambient.reset_news_cache()


def test_condition_label_maps_codes_and_unknowns():
    assert ambient.condition_label(0) == "Clear sky"
    assert ambient.condition_label(63) == "Rain"
    assert ambient.condition_label(12345) == "Unknown"
    assert ambient.condition_label(None) == "Unknown"


def test_fetch_weather_formats_live_values(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"current": {"temperature_2m": 33.6, "weather_code": 2}}
        ),
    )
    out = asyncio.run(ambient.fetch_weather(24.7, 46.7, "Riyadh"))
    assert out == {"temp": "34 °C", "condition": "Partly cloudy", "city": "Riyadh"}


def test_fetch_weather_raises_when_upstream_fails(monkeypatch):
    _patch_client(monkeypatch, lambda req: httpx.Response(500))
    with pytest.raises(ambient.AmbientUnavailable):
        asyncio.run(ambient.fetch_weather(1, 1, "x"))


def test_fetch_weather_raises_on_missing_temperature(monkeypatch):
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={"current": {}}))
    with pytest.raises(ambient.AmbientUnavailable):
        asyncio.run(ambient.fetch_weather(1, 1, "x"))


def _hn_handler(req):
    if req.url.path.endswith("topstories.json"):
        return httpx.Response(200, json=[11, 22, 33])
    story_id = int(req.url.path.split("/")[-1].split(".")[0])
    titles = {11: "Story A", 22: "Story B", 33: None}
    return httpx.Response(200, json={"title": titles[story_id]})


def test_fetch_news_returns_real_titles_and_skips_untitled(monkeypatch):
    _patch_client(monkeypatch, _hn_handler)
    items = asyncio.run(ambient.fetch_news())
    assert [i["title"] for i in items] == ["Story A", "Story B"]
    assert all(i["source"] == "Hacker News" for i in items)


def test_fetch_news_is_cached(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return _hn_handler(req)

    _patch_client(monkeypatch, handler)
    asyncio.run(ambient.fetch_news())
    first = len(calls)
    asyncio.run(ambient.fetch_news())
    assert len(calls) == first


def test_news_endpoint_returns_empty_list_when_upstream_down(monkeypatch):
    _patch_client(monkeypatch, lambda req: httpx.Response(503))
    out = asyncio.run(dashboard.list_news())
    assert out == {"data": [], "total": 0}


def test_weather_endpoint_without_integration_is_honest():
    out = asyncio.run(dashboard.get_weather(USER, FakeDB(None)))
    assert out["data"]["temp"] == "—"
    assert "Open-Meteo" in out["data"]["condition"]


def test_weather_endpoint_live_for_connected_integration(monkeypatch):
    _patch_client(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"current": {"temperature_2m": 21.2, "weather_code": 0}}
        ),
    )
    integration = SimpleNamespace(
        config={"latitude": 24.7, "longitude": 46.7, "city": "Riyadh"}
    )
    out = asyncio.run(dashboard.get_weather(USER, FakeDB(integration)))
    assert out["data"] == {"temp": "21 °C", "condition": "Clear sky", "city": "Riyadh"}


def test_weather_endpoint_survives_upstream_failure(monkeypatch):
    _patch_client(monkeypatch, lambda req: httpx.Response(500))
    integration = SimpleNamespace(config={"latitude": 1.0, "longitude": 2.0})
    out = asyncio.run(dashboard.get_weather(USER, FakeDB(integration)))
    assert out["data"]["temp"] == "—"
    assert out["data"]["city"] == "1.00, 2.00"


def test_commute_is_honestly_unconfigured():
    out = asyncio.run(dashboard.get_commute())
    assert out["data"]["eta"] == "—"


def test_health_habits_endpoint_survives_one_source_failing(monkeypatch):
    from fastapi.responses import JSONResponse
    from src.api.v1 import apple_health, whoop

    async def whoop_ok(current_user, db):
        return JSONResponse({"data": {"recovery": {"recovery_score": 70}}})

    async def apple_boom(current_user, db):
        raise RuntimeError("redis down")

    monkeypatch.setattr(whoop, "get_dashboard", whoop_ok)
    monkeypatch.setattr(apple_health, "get_dashboard", apple_boom)
    out = asyncio.run(dashboard.list_health_habits(USER, FakeDB(None)))
    assert out["total"] == 1
    assert out["data"][0]["name"] == "Recovery"


def test_events_and_briefing_never_fall_back_to_fake_rows(monkeypatch):
    async def no_token(*_a, **_k):
        raise dashboard.TokenUnavailableError("none")

    monkeypatch.setattr(dashboard, "get_valid_google_token", no_token)
    events = asyncio.run(dashboard.list_events(USER, FakeDB(None)))
    assert events == {"data": [], "total": 0}
    briefing = asyncio.run(dashboard.get_briefing(USER, FakeDB(None)))
    assert "Connect Google" in briefing["data"]["summary"]
    assert "portfolio" not in briefing["data"]["summary"].lower()


def test_events_empty_when_live_fetch_fails(monkeypatch):
    async def token(*_a, **_k):
        return "tok"

    async def boom(_token):
        raise RuntimeError("google 500")

    monkeypatch.setattr(dashboard, "get_valid_google_token", token)
    monkeypatch.setattr(dashboard, "fetch_todays_events", boom)
    assert asyncio.run(dashboard.list_events(USER, FakeDB(None))) == {
        "data": [],
        "total": 0,
    }
