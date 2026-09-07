"""Characterisation tests for the Whoop wire parsers and sport table.

These functions were extracted verbatim out of api/v1/whoop.py during the
FEAT-120 restructure. The tests pin the behaviour that move had to
preserve — above all the handling of Whoop's partially-populated records,
which is what stops one in-progress record from blanking a whole card.
"""

import pytest
from src.services.whoop.parsers import (
    parse_hrv_trend,
    parse_recovery,
    parse_sleep,
    parse_strain,
    parse_workout,
    records_of,
)
from src.services.whoop.sports import sport_name

# ── records_of ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"records": [{"id": 1}]}, [{"id": 1}]),
        ({"records": []}, []),
        ({"records": None}, []),
        ({}, []),
        (None, []),
        ("not-a-dict", []),
    ],
)
def test_records_of_tolerates_missing_and_null_records(body, expected):
    assert records_of(body) == expected


# ── sport_name ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sport_id,expected",
    [
        (0, "Running"),
        (1, "Cycling"),
        (45, "Weightlifting"),
        (-1, "Activity"),
        (None, "Activity"),
        (99999, "Activity"),
    ],
)
def test_sport_name_falls_back_for_unknown_ids(sport_id, expected):
    assert sport_name(sport_id) == expected


# ── score-less records must not raise ───────────────────────────────────


@pytest.mark.parametrize(
    "parse",
    [parse_recovery, parse_sleep, parse_strain, parse_workout],
)
@pytest.mark.parametrize("record", [{}, {"score": None}, {"id": 7, "score": {}}])
def test_parsers_degrade_to_empty_fields_when_score_absent(parse, record):
    """Whoop omits `score` while a record is still being computed, and can
    send it explicitly null. Both must yield a model with empty fields
    rather than raising — a raise here would blank the entire dashboard.
    """
    result = parse(record)
    assert result is not None


def test_parse_recovery_reads_nested_score_fields():
    record = {
        "cycle_id": 12,
        "created_at": "2026-09-01T06:00:00.000Z",
        "score": {
            "recovery_score": 78,
            "hrv_rmssd_milli": 94.2,
            "resting_heart_rate": 48,
            "spo2_percentage": 96.5,
        },
    }
    recovery = parse_recovery(record)
    assert recovery.recovery_score == 78
    assert recovery.hrv_rmssd_milli == 94.2
    assert recovery.resting_heart_rate == 48
    assert recovery.spo2_percentage == 96.5
    assert recovery.cycle_id == 12


def test_parse_sleep_reads_stage_summary_two_levels_down():
    record = {
        "id": 5,
        "score": {
            "sleep_performance_percentage": 91,
            "stage_summary": {
                "total_rem_sleep_time_milli": 5_400_000,
                "total_slow_wave_sleep_time_milli": 3_600_000,
            },
        },
    }
    sleep = parse_sleep(record)
    assert sleep.sleep_performance_percentage == 91
    assert sleep.total_rem_sleep_time_milli == 5_400_000
    assert sleep.total_slow_wave_sleep_time_milli == 3_600_000


def test_parse_strain_maps_score_strain_onto_score_field():
    """The wire calls it score.strain; the response schema calls it score."""
    strain = parse_strain({"id": 3, "score": {"strain": 14.7, "kilojoule": 9000}})
    assert strain.score == 14.7
    assert strain.kilojoule == 9000


def test_parse_workout_resolves_sport_name_from_id():
    workout = parse_workout({"id": 1, "sport_id": 44, "score": {"strain": 8.1}})
    assert workout.sport_name == "Yoga"
    assert workout.strain == 8.1


# ── HRV trend ordering ──────────────────────────────────────────────────


def test_parse_hrv_trend_reverses_to_oldest_first_and_truncates_date():
    body = {
        "records": [
            {"created_at": "2026-09-03T06:00:00.000Z", "score": {"hrv_rmssd_milli": 3}},
            {"created_at": "2026-09-02T06:00:00.000Z", "score": {"hrv_rmssd_milli": 2}},
            {"created_at": "2026-09-01T06:00:00.000Z", "score": {"hrv_rmssd_milli": 1}},
        ]
    }
    points = parse_hrv_trend(body)
    assert [p.date for p in points] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert [p.hrv_rmssd_milli for p in points] == [1, 2, 3]


def test_parse_hrv_trend_drops_records_with_no_timestamp():
    """A point with no created_at has no x-axis position to plot at."""
    body = {
        "records": [
            {"created_at": "2026-09-02T06:00:00.000Z", "score": {"hrv_rmssd_milli": 2}},
            {"score": {"hrv_rmssd_milli": 9}},
            {"created_at": None, "score": {"hrv_rmssd_milli": 9}},
        ]
    }
    points = parse_hrv_trend(body)
    assert len(points) == 1
    assert points[0].date == "2026-09-02"
