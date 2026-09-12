"""AppleHealthIngestPayload plausibility bounds, coercion, and state invariants.

The ingest payload is the only untrusted boundary in this feature: it is
POSTed by a user-configured iOS Shortcut or a third-party exporter whose
schema drifts between app versions. Two deliberate design decisions live
in that model and had no test anywhere before this file:

  1. Out-of-range readings are clamped to None and reported back in
     `dropped_fields`, rather than 422-ing the whole push. One bad sensor
     sample must not discard the other five good metrics.
  2. Numeric values may arrive as JSON strings ("58"). The bounds check is
     a mode='after' validator precisely so Pydantic has already coerced
     them; a mode='before' check would raise TypeError comparing str to int.

AppleHealthSnapshot's illegal-state invariant (no readings while
disconnected or stale) is covered here too, since it is the other half of
the same schema contract.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from src.schemas.apple_health import AppleHealthIngestPayload, AppleHealthSnapshot

# Mirrors _BOUNDS in src/schemas/apple_health.py. Duplicated on purpose:
# importing the private constant would make these tests agree with the
# implementation by construction even if the bounds were wrong.
BOUNDS = {
    "resting_heart_rate": (20, 250),
    "heart_rate_variability_ms": (5, 500),
    "sleep_hours": (0, 24),
    "active_energy_kcal": (0, 10_000),
    "steps": (0, 200_000),
    "vo2_max": (0, 100),
}


# ── Happy path ───────────────────────────────────────────────────────────


def test_all_valid_fields_accepted_with_empty_dropped_list():
    payload = AppleHealthIngestPayload(
        resting_heart_rate=65.0,
        heart_rate_variability_ms=45.0,
        sleep_hours=7.5,
        active_energy_kcal=600.0,
        steps=10_000,
        vo2_max=42.0,
        recorded_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    assert payload.resting_heart_rate == 65.0
    assert payload.steps == 10_000
    assert payload.dropped_fields == []


def test_all_none_payload_is_valid():
    """A Shortcut that can only supply some metrics still produces a valid
    push; every field is independently optional."""
    payload = AppleHealthIngestPayload()
    assert payload.dropped_fields == []
    assert payload.resting_heart_rate is None


def test_extra_unknown_fields_are_ignored_not_rejected():
    """extra='ignore' — a new field in the exporter's schema must not 422
    the whole push, and must not be reported as a dropped biometric."""
    payload = AppleHealthIngestPayload(
        **{
            "resting_heart_rate": 70.0,
            "unknown_sensor_reading": 99.9,
            "future_field": "x",
        }
    )
    assert payload.resting_heart_rate == 70.0
    assert payload.dropped_fields == []


# ── Bounds: clamp-to-None + dropped_fields ───────────────────────────────


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("resting_heart_rate", 19.9),
        ("heart_rate_variability_ms", 4.9),
        ("sleep_hours", -0.1),
        ("active_energy_kcal", -1.0),
        ("steps", -1),
        ("vo2_max", -0.1),
    ],
)
def test_field_below_minimum_is_clamped_to_none_and_listed(field, bad_value):
    payload = AppleHealthIngestPayload(**{field: bad_value})
    assert getattr(payload, field) is None
    assert payload.dropped_fields == [field]


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("resting_heart_rate", 250.1),
        ("heart_rate_variability_ms", 500.1),
        ("sleep_hours", 24.1),
        ("active_energy_kcal", 10_000.1),
        ("steps", 200_001),
        ("vo2_max", 100.1),
    ],
)
def test_field_above_maximum_is_clamped_to_none_and_listed(field, bad_value):
    payload = AppleHealthIngestPayload(**{field: bad_value})
    assert getattr(payload, field) is None
    assert payload.dropped_fields == [field]


@pytest.mark.parametrize("field,bounds", list(BOUNDS.items()))
def test_boundary_values_are_inclusive(field, bounds):
    """lo <= v <= hi — a resting heart rate of exactly 20 is implausible-
    adjacent but real, and must not be silently discarded."""
    lo, hi = bounds
    for value in (lo, hi):
        payload = AppleHealthIngestPayload(**{field: value})
        assert getattr(payload, field) == value
        assert payload.dropped_fields == []


def test_one_bad_field_does_not_discard_the_good_ones():
    """The whole reason bounds clamp instead of reject."""
    payload = AppleHealthIngestPayload(
        resting_heart_rate=9999.0,  # implausible
        sleep_hours=7.5,
        steps=8_000,
    )
    assert payload.resting_heart_rate is None
    assert payload.dropped_fields == ["resting_heart_rate"]
    assert payload.sleep_hours == 7.5
    assert payload.steps == 8_000


def test_multiple_out_of_range_fields_are_all_listed():
    payload = AppleHealthIngestPayload(
        resting_heart_rate=0.0,
        sleep_hours=999.0,
        vo2_max=-5.0,
    )
    assert sorted(payload.dropped_fields) == [
        "resting_heart_rate",
        "sleep_hours",
        "vo2_max",
    ]


def test_dropped_fields_is_not_shared_between_instances():
    """PrivateAttr(default_factory=list) — a mutable default shared across
    instances would leak one user's dropped fields into another's response."""
    bad = AppleHealthIngestPayload(resting_heart_rate=9999.0)
    good = AppleHealthIngestPayload(resting_heart_rate=60.0)
    assert bad.dropped_fields == ["resting_heart_rate"]
    assert good.dropped_fields == []


# ── Numeric-string coercion (Health Auto Export emits numerics as strings) ──


@pytest.mark.parametrize(
    "field,string_value,expected",
    [
        ("resting_heart_rate", "58", 58.0),
        ("heart_rate_variability_ms", "43.5", 43.5),
        ("sleep_hours", "7", 7.0),
        ("active_energy_kcal", "450", 450.0),
        ("steps", "8000", 8000),
        ("vo2_max", "38.2", 38.2),
    ],
)
def test_numeric_string_input_coerced_without_type_error(field, string_value, expected):
    """Regression guard for the mode='after' choice: a mode='before' bounds
    validator would raise TypeError comparing "58" against an int bound."""
    payload = AppleHealthIngestPayload(**{field: string_value})
    assert getattr(payload, field) == pytest.approx(expected)
    assert payload.dropped_fields == []


def test_out_of_range_numeric_string_is_still_clamped():
    payload = AppleHealthIngestPayload(resting_heart_rate="9999")
    assert payload.resting_heart_rate is None
    assert payload.dropped_fields == ["resting_heart_rate"]


# ── recorded_at coercion ─────────────────────────────────────────────────


def test_recorded_at_in_the_future_is_coerced_to_none():
    """A device clock set wrong must not produce a reading dated ahead of
    now, which would make the dashboard's freshness logic nonsense."""
    payload = AppleHealthIngestPayload(
        recorded_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert payload.recorded_at is None


def test_recorded_at_unparseable_string_is_coerced_to_none_not_422():
    payload = AppleHealthIngestPayload(recorded_at="not-a-datetime")
    assert payload.recorded_at is None


def test_recorded_at_past_datetime_is_preserved():
    past = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert AppleHealthIngestPayload(recorded_at=past).recorded_at == past


def test_recorded_at_z_suffix_is_accepted_and_tz_aware():
    """Health Auto Export emits 'Z' rather than '+00:00'."""
    payload = AppleHealthIngestPayload(recorded_at="2024-03-15T08:30:00Z")
    assert payload.recorded_at is not None
    assert payload.recorded_at.tzinfo is not None


def test_recorded_at_naive_datetime_is_assumed_utc():
    payload = AppleHealthIngestPayload(recorded_at="2024-03-15T08:30:00")
    assert payload.recorded_at is not None
    assert payload.recorded_at.tzinfo is not None
    assert payload.recorded_at.utcoffset() == timedelta(0)


def test_recorded_at_non_datetime_type_is_coerced_to_none():
    assert AppleHealthIngestPayload(recorded_at=12345).recorded_at is None


# ── Logging: field name yes, biometric value no ──────────────────────────


def test_out_of_range_warning_logs_field_name_but_not_the_value(caplog):
    """Biometric values must not leak into log files — the WARNING names the
    field that was dropped and stops there."""
    with caplog.at_level(logging.WARNING, logger="src.schemas.apple_health"):
        AppleHealthIngestPayload(resting_heart_rate=9999.0)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("resting_heart_rate" in r.getMessage() for r in warnings)
    assert not any("9999" in r.getMessage() for r in warnings)


# ── AppleHealthSnapshot: illegal-state invariant + wire shape ────────────


def test_from_ingest_maps_every_payload_field():
    """Spreading model_dump() is what stops a newly added metric from being
    silently dropped on the way to the dashboard."""
    payload = AppleHealthIngestPayload(
        resting_heart_rate=68.0,
        heart_rate_variability_ms=50.0,
        sleep_hours=6.5,
        active_energy_kcal=300.0,
        steps=5_000,
        vo2_max=38.0,
    )
    now = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
    snapshot = AppleHealthSnapshot.from_ingest(payload, received_at=now)

    for field in BOUNDS:
        assert getattr(snapshot, field) == getattr(payload, field)
    assert snapshot.received_at == now
    assert snapshot.connected is True
    assert snapshot.stale is False


def test_snapshot_rejects_readings_while_disconnected():
    with pytest.raises(ValidationError):
        AppleHealthSnapshot(connected=False, resting_heart_rate=60.0)


def test_snapshot_rejects_readings_while_stale():
    with pytest.raises(ValidationError):
        AppleHealthSnapshot(connected=True, stale=True, resting_heart_rate=60.0)


def test_snapshot_allows_the_three_states_the_api_actually_emits():
    assert AppleHealthSnapshot(connected=False).connected is False
    assert AppleHealthSnapshot(connected=True, stale=True).stale is True
    assert AppleHealthSnapshot(connected=True, resting_heart_rate=60.0).stale is False


def test_snapshot_model_dump_json_serialises_datetimes_as_strings():
    """mode='json' is what the dashboard endpoint puts on the wire."""
    dumped = AppleHealthSnapshot(
        connected=True,
        resting_heart_rate=65.0,
        recorded_at=datetime(2024, 6, 1, 11, 0, tzinfo=timezone.utc),
        received_at=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
    ).model_dump(mode="json")

    assert isinstance(dumped["recorded_at"], str)
    assert isinstance(dumped["received_at"], str)
