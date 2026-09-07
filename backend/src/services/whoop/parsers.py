"""Whoop wire-format -> response-schema translation.

Pure functions: dict in, Pydantic model out. No I/O, no DB, no FastAPI, so
Whoop's response quirks (score nested one level down, stage_summary nested
two) are covered by plain unit tests with literal fixtures.

Every field is optional on the way in. Whoop omits `score` entirely while a
record is still being computed, so `record.get("score") or {}` is load
bearing: a present-but-null `score` must degrade to empty fields rather
than raising and blanking the whole dashboard.
"""

from __future__ import annotations

from typing import Any

from ...schemas.whoop import (
    WhoopHRVPoint,
    WhoopRecovery,
    WhoopSleep,
    WhoopStrain,
    WhoopWorkout,
)
from .sports import sport_name


def _score(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("score") or {}


def parse_recovery(record: dict[str, Any]) -> WhoopRecovery:
    score = _score(record)
    return WhoopRecovery(
        recovery_score=score.get("recovery_score"),
        hrv_rmssd_milli=score.get("hrv_rmssd_milli"),
        resting_heart_rate=score.get("resting_heart_rate"),
        skin_temp_celsius=score.get("skin_temp_celsius"),
        spo2_percentage=score.get("spo2_percentage"),
        cycle_id=record.get("cycle_id"),
        created_at=record.get("created_at"),
    )


def parse_sleep(record: dict[str, Any]) -> WhoopSleep:
    score = _score(record)
    stage = score.get("stage_summary") or {}
    return WhoopSleep(
        id=record.get("id"),
        start=record.get("start"),
        end=record.get("end"),
        total_in_bed_time_milli=stage.get("total_in_bed_time_milli"),
        total_awake_time_milli=stage.get("total_awake_time_milli"),
        total_no_data_time_milli=stage.get("total_no_data_time_milli"),
        total_light_sleep_time_milli=stage.get("total_light_sleep_time_milli"),
        total_slow_wave_sleep_time_milli=stage.get("total_slow_wave_sleep_time_milli"),
        total_rem_sleep_time_milli=stage.get("total_rem_sleep_time_milli"),
        sleep_performance_percentage=score.get("sleep_performance_percentage"),
        sleep_consistency_percentage=score.get("sleep_consistency_percentage"),
        sleep_efficiency_percentage=score.get("sleep_efficiency_percentage"),
        respiratory_rate=score.get("respiratory_rate"),
    )


def parse_strain(record: dict[str, Any]) -> WhoopStrain:
    score = _score(record)
    return WhoopStrain(
        id=record.get("id"),
        start=record.get("start"),
        end=record.get("end"),
        score=score.get("strain"),
        kilojoule=score.get("kilojoule"),
        average_heart_rate=score.get("average_heart_rate"),
        max_heart_rate=score.get("max_heart_rate"),
    )


def parse_workout(record: dict[str, Any]) -> WhoopWorkout:
    score = _score(record)
    return WhoopWorkout(
        id=record.get("id"),
        sport_id=record.get("sport_id"),
        sport_name=sport_name(record.get("sport_id")),
        start=record.get("start"),
        end=record.get("end"),
        strain=score.get("strain"),
        average_heart_rate=score.get("average_heart_rate"),
        max_heart_rate=score.get("max_heart_rate"),
        kilojoule=score.get("kilojoule"),
    )


def records_of(body: Any) -> list[dict[str, Any]]:
    """Whoop paginates everything under a `records` key.

    Tolerates a missing key and an explicit null alike — both mean "no data
    yet", which is an empty card, not an error.
    """
    if not isinstance(body, dict):
        return []
    return body.get("records") or []


def parse_hrv_trend(body: Any) -> list[WhoopHRVPoint]:
    """Oldest-first HRV series for the sparkline.

    Whoop returns newest-first; the chart plots left-to-right in time, so
    the order is reversed here rather than in the view. Records with no
    `created_at` are dropped — they have no x-axis position to plot at.
    """
    return [
        WhoopHRVPoint(
            date=record.get("created_at", "")[:10],
            hrv_rmssd_milli=(record.get("score") or {}).get("hrv_rmssd_milli"),
        )
        for record in reversed(records_of(body))
        if record.get("created_at")
    ]
