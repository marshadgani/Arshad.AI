"""Unit tests for backend/src/services/weather/conditions.py.

Pure parsing, no I/O, no fixtures. Both from_upstream() (untrusted
OpenWeatherMap body) and from_cache() (untrusted Redis payload) must
degrade per-field on malformed/missing input rather than raise — the
service.py decision tree has no except clause around either call, so a
KeyError/TypeError here would surface as a 500 instead of a degraded tile.

These paths were previously only exercised indirectly through
test_weather_service.py's single fixed happy-path payload, which never
touched the None-safety branches below.
"""

from __future__ import annotations

from backend.src.services.weather.conditions import CurrentConditions

# ---------------------------------------------------------------------------
# from_upstream — happy path
# ---------------------------------------------------------------------------


def test_from_upstream_parses_full_body():
    raw = {
        "main": {"temp": 15.2},
        "weather": [{"main": "Clouds"}],
        "name": "London",
    }
    result = CurrentConditions.from_upstream(raw)
    assert result.temp == "15 °C"
    assert result.condition == "Clouds"
    assert result.city == "London"


def test_from_upstream_rounds_temperature():
    """round() must be applied — 15.6 must render as 16 °C, not truncate."""
    raw = {"main": {"temp": 15.6}, "weather": [{"main": "Clear"}], "name": "Paris"}
    result = CurrentConditions.from_upstream(raw)
    assert result.temp == "16 °C"


def test_from_upstream_rounds_negative_temperature():
    raw = {"main": {"temp": -3.7}, "weather": [{"main": "Snow"}], "name": "Oslo"}
    result = CurrentConditions.from_upstream(raw)
    assert result.temp == "-4 °C"


def test_from_upstream_accepts_integer_temp():
    """OpenWeatherMap may return an int, not just a float."""
    raw = {"main": {"temp": 20}, "weather": [{"main": "Clear"}], "name": "Rome"}
    result = CurrentConditions.from_upstream(raw)
    assert result.temp == "20 °C"


# ---------------------------------------------------------------------------
# from_upstream — missing/malformed fields must degrade to None, not raise
# ---------------------------------------------------------------------------


def test_from_upstream_missing_main_key():
    result = CurrentConditions.from_upstream(
        {"weather": [{"main": "Clouds"}], "name": "X"}
    )
    assert result.temp is None
    assert result.condition == "Clouds"


def test_from_upstream_main_is_not_a_dict():
    """A malformed body where 'main' is e.g. null must not raise."""
    result = CurrentConditions.from_upstream({"main": None, "weather": [], "name": "X"})
    assert result.temp is None


def test_from_upstream_temp_is_non_numeric_string():
    """A string temp (malformed upstream body) must degrade to None, not be
    passed to round() and raise a TypeError."""
    raw = {"main": {"temp": "hot"}, "weather": [{"main": "Clear"}], "name": "X"}
    result = CurrentConditions.from_upstream(raw)
    assert result.temp is None


def test_from_upstream_missing_weather_key():
    result = CurrentConditions.from_upstream({"main": {"temp": 10}, "name": "X"})
    assert result.condition is None
    assert result.temp == "10 °C"


def test_from_upstream_empty_weather_list():
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 10}, "weather": [], "name": "X"}
    )
    assert result.condition is None


def test_from_upstream_weather_entry_missing_main_key():
    """A weather[0] dict without a 'main' key must not raise KeyError."""
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 10}, "weather": [{"description": "clear sky"}], "name": "X"}
    )
    assert result.condition is None


def test_from_upstream_missing_name_key():
    result = CurrentConditions.from_upstream({"main": {"temp": 10}, "weather": []})
    assert result.city is None


def test_from_upstream_name_is_empty_string():
    """An empty-string city name must normalise to None (falsy), not ''."""
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 10}, "weather": [], "name": ""}
    )
    assert result.city is None


def test_from_upstream_temp_zero_is_not_treated_as_missing():
    """0°C is falsy but a legitimate value — must not be coerced to None by
    a truthiness check instead of an isinstance check."""
    raw = {"main": {"temp": 0}, "weather": [{"main": "Snow"}], "name": "X"}
    result = CurrentConditions.from_upstream(raw)
    assert result.temp == "0 °C"


# ---------------------------------------------------------------------------
# from_cache — round-trip and defensive reconstruction
# ---------------------------------------------------------------------------


def test_from_cache_round_trip():
    payload = {"temp": "15 °C", "condition": "Clouds", "city": "London"}
    result = CurrentConditions.from_cache(payload)
    assert result.temp == "15 °C"
    assert result.condition == "Clouds"
    assert result.city == "London"


def test_from_cache_missing_keys_become_none():
    result = CurrentConditions.from_cache({})
    assert result.temp is None
    assert result.condition is None
    assert result.city is None


def test_from_cache_ignores_unknown_keys():
    """A cache entry written by a future/older parser shape with extra keys
    must not raise TypeError (regression guard: from_cache is deliberately
    not cls(**payload))."""
    payload = {
        "temp": "15 °C",
        "condition": "Clouds",
        "city": "London",
        "unexpected_future_field": "value",
    }
    result = CurrentConditions.from_cache(payload)
    assert result.temp == "15 °C"


def test_as_cache_payload_round_trips_through_from_cache():
    original = CurrentConditions(temp="15 °C", condition="Clouds", city="London")
    reconstructed = CurrentConditions.from_cache(original.as_cache_payload())
    assert reconstructed == original


# ---------------------------------------------------------------------------
# Regression — value-type normalisation (not just key presence)
#
# Reading keys individually defends against a *renamed* field but not a
# *retyped* one. Every case below raised (AttributeError from from_upstream,
# or a WeatherResponse ValidationError one layer after from_cache) until
# _as_mapping/_as_text were introduced.
# ---------------------------------------------------------------------------


def test_from_upstream_weather_list_of_non_mappings_does_not_raise():
    """`weather: ["Clouds"]` — a present-but-wrong-typed member. Previously
    `conditions[0].get("main")` raised AttributeError out of a function whose
    job is to absorb exactly this."""
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 15.2}, "weather": ["Clouds"], "name": "London"}
    )
    assert result.condition is None
    assert result.temp == "15 °C"
    assert result.city == "London"


def test_from_upstream_weather_list_of_none_does_not_raise():
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 15.2}, "weather": [None], "name": "London"}
    )
    assert result.condition is None


def test_from_upstream_non_mapping_main_does_not_raise():
    """`main: "n/a"` is truthy, so `raw.get("main") or {}` let it through to
    `.get`."""
    result = CurrentConditions.from_upstream(
        {"main": "n/a", "weather": [{"main": "Clouds"}], "name": "London"}
    )
    assert result.temp is None
    assert result.condition == "Clouds"


def test_from_upstream_non_list_weather_does_not_raise():
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 15.2}, "weather": "Clouds", "name": "London"}
    )
    assert result.condition is None


def test_from_upstream_bool_temp_is_not_rendered_as_a_temperature():
    """bool is an int subclass, so `isinstance(True, (int, float))` passed and
    `round(True)` rendered a confident '1 °C'."""
    result = CurrentConditions.from_upstream(
        {"main": {"temp": True}, "weather": [{"main": "Clouds"}], "name": "London"}
    )
    assert result.temp is None


def test_from_upstream_blank_city_becomes_none():
    """A whitespace-only name must not render as an empty slot in the card."""
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 15.2}, "weather": [{"main": "Clouds"}], "name": "   "}
    )
    assert result.city is None


def test_from_upstream_non_string_condition_becomes_none():
    result = CurrentConditions.from_upstream(
        {"main": {"temp": 15.2}, "weather": [{"main": 42}], "name": "London"}
    )
    assert result.condition is None


def test_from_cache_numeric_temp_becomes_none_not_a_validation_error():
    """A stored `{"temp": 15.2}` (a plausible earlier shape, before the
    '°C' suffix moved into this module) reached WeatherResponse, whose `str`
    field Pydantic v2 rejects rather than coerces — pinning the tile to its
    unavailable state for the rest of the 600s TTL."""
    result = CurrentConditions.from_cache(
        {"temp": 15.2, "condition": "Clear", "city": "London"}
    )
    assert result.temp is None
    assert result.condition == "Clear"


def test_from_cache_non_scalar_values_become_none():
    result = CurrentConditions.from_cache({"temp": ["a"], "condition": {}, "city": 7})
    assert result == CurrentConditions()


# ---------------------------------------------------------------------------
# is_renderable — drives the cache-eviction branch in service.py
# ---------------------------------------------------------------------------


def test_is_renderable_true_when_temp_present():
    assert CurrentConditions(temp="15 °C").is_renderable is True


def test_is_renderable_false_when_temp_absent():
    """Matches WeatherCard's own live-branch key (`data.temp == null`)."""
    assert CurrentConditions(condition="Clear", city="London").is_renderable is False


def test_is_renderable_false_for_empty_conditions():
    assert CurrentConditions().is_renderable is False
