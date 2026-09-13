"""Unit tests for the WeatherResponse state-machine validator.

No I/O, no DB, no fixtures. These lock in the four legal
connected/needs_reauth/degraded combinations independently of the service,
so a change to the decision tree cannot quietly widen what the schema
accepts.

The invariant worth protecting: payload fields are populated *only* in the
connected-and-healthy state. Without it, `connected=False, temp="28 °C"` —
exactly the seeded-mock shape FEAT-138 removed — is representable again.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.src.schemas.dashboard import WeatherResponse

# ---------------------------------------------------------------------------
# The four legal states
# ---------------------------------------------------------------------------


def test_never_connected_state_is_valid():
    resp = WeatherResponse(connected=False)
    assert (resp.connected, resp.needs_reauth, resp.degraded) == (False, False, False)
    assert (resp.temp, resp.condition, resp.city) == (None, None, None)


def test_connected_needs_reauth_state_is_valid():
    resp = WeatherResponse(connected=True, needs_reauth=True)
    assert resp.needs_reauth is True
    assert resp.temp is None


def test_connected_degraded_state_is_valid():
    resp = WeatherResponse(connected=True, degraded=True)
    assert resp.degraded is True
    assert resp.temp is None


def test_connected_healthy_with_payload_is_valid():
    resp = WeatherResponse(
        connected=True, temp="15 °C", condition="Clouds", city="London"
    )
    assert (resp.temp, resp.condition, resp.city) == ("15 °C", "Clouds", "London")


def test_connected_healthy_with_partial_payload_is_valid():
    """Upstream omits fields freely and conditions.py degrades per-field, so
    the healthy state must tolerate a partly-empty payload."""
    resp = WeatherResponse(connected=True, temp="10 °C")
    assert resp.condition is None
    assert resp.city is None


def test_connected_healthy_with_empty_payload_is_valid():
    """The cache-eviction branch in service.py depends on this being
    constructible rather than raising."""
    assert WeatherResponse(connected=True).temp is None


# ---------------------------------------------------------------------------
# Illegal combinations
# ---------------------------------------------------------------------------


def test_disconnected_with_payload_is_rejected():
    """The seeded-mock shape. This is the assertion that makes reintroducing
    it a test failure rather than a silent regression."""
    with pytest.raises(ValidationError):
        WeatherResponse(connected=False, temp="28 °C", city="Bengaluru")


def test_disconnected_with_needs_reauth_is_rejected():
    with pytest.raises(ValidationError):
        WeatherResponse(connected=False, needs_reauth=True)


def test_disconnected_with_degraded_is_rejected():
    with pytest.raises(ValidationError):
        WeatherResponse(connected=False, degraded=True)


def test_needs_reauth_and_degraded_together_is_rejected():
    with pytest.raises(ValidationError):
        WeatherResponse(connected=True, needs_reauth=True, degraded=True)


def test_needs_reauth_with_payload_is_rejected():
    """A "reconnect" prompt must never sit next to stale figures."""
    with pytest.raises(ValidationError):
        WeatherResponse(connected=True, needs_reauth=True, temp="15 °C")


def test_degraded_with_payload_is_rejected():
    with pytest.raises(ValidationError):
        WeatherResponse(connected=True, degraded=True, condition="Clear")


# ---------------------------------------------------------------------------
# Value typing — Pydantic v2 rejects rather than coerces
# ---------------------------------------------------------------------------


def test_numeric_temp_is_rejected_not_coerced():
    """Documents why conditions.py must normalise value types itself: v2
    does not turn 15.2 into "15.2"."""
    with pytest.raises(ValidationError):
        WeatherResponse(connected=True, temp=15.2)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Frozen
# ---------------------------------------------------------------------------


def test_model_is_frozen():
    """The validator runs only on construction, so mutability would let a
    field be reassigned into a combination nothing re-checks."""
    resp = WeatherResponse(connected=True, temp="15 °C")
    with pytest.raises(ValidationError):
        resp.temp = "0 °C"  # type: ignore[misc]
