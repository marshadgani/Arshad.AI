"""Pydantic response schemas for Whoop health data endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class WhoopRecovery(BaseModel):
    recovery_score: Optional[float] = None
    hrv_rmssd_milli: Optional[float] = None
    resting_heart_rate: Optional[float] = None
    skin_temp_celsius: Optional[float] = None
    spo2_percentage: Optional[float] = None
    cycle_id: Optional[int] = None
    created_at: Optional[str] = None


class WhoopSleep(BaseModel):
    id: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    total_in_bed_time_milli: Optional[int] = None
    total_awake_time_milli: Optional[int] = None
    total_no_data_time_milli: Optional[int] = None
    total_light_sleep_time_milli: Optional[int] = None
    total_slow_wave_sleep_time_milli: Optional[int] = None
    total_rem_sleep_time_milli: Optional[int] = None
    sleep_performance_percentage: Optional[float] = None
    sleep_consistency_percentage: Optional[float] = None
    sleep_efficiency_percentage: Optional[float] = None
    respiratory_rate: Optional[float] = None


class WhoopStrain(BaseModel):
    id: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    score: Optional[float] = None
    kilojoule: Optional[float] = None
    average_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None


class WhoopDashboard(BaseModel):
    connected: bool
    needs_reauth: bool = False
    degraded: bool = Field(
        default=False,
        description="True when a transient upstream failure (network "
        "timeout, Whoop 5xx) forced null biometric fields, as distinct "
        "from a genuine no-data-recorded-today response. The connection "
        "itself is fine; retry later.",
    )
    recovery: Optional[WhoopRecovery] = None
    sleep: Optional[WhoopSleep] = None
    strain: Optional[WhoopStrain] = None
    user_first_name: Optional[str] = None

    @model_validator(mode="after")
    def _check_state_combination(self) -> "WhoopDashboard":
        """connected/needs_reauth/degraded were three independent bools —
        8 representable combinations for a state machine with 4 legal
        ones (see api/v1/whoop.py's four WhoopDashboard(...) call sites:
        disconnected; connected+needs_reauth; connected+degraded;
        connected+healthy). Nothing stopped a future edit from
        constructing e.g. connected=False, needs_reauth=True — a
        dashboard the frontend has no rendering branch for. This closes
        the gap without changing the wire shape any existing consumer
        depends on.
        """
        if not self.connected and (self.needs_reauth or self.degraded):
            raise ValueError(
                "needs_reauth/degraded require connected=True — a "
                "disconnected dashboard has no Whoop session to be "
                "degraded or expired."
            )
        if self.needs_reauth and self.degraded:
            raise ValueError(
                "needs_reauth and degraded are mutually exclusive — "
                "re-auth is required before another fetch can even be "
                "attempted, so a transient-failure state is undefined."
            )
        if (self.needs_reauth or self.degraded or not self.connected) and (
            self.recovery is not None
            or self.sleep is not None
            or self.strain is not None
        ):
            raise ValueError(
                "recovery/sleep/strain must be null whenever the "
                "dashboard is disconnected, needs re-auth, or degraded — "
                "those are the states with no fresh Whoop data behind "
                "them."
            )
        return self


class WhoopHRVPoint(BaseModel):
    date: str
    hrv_rmssd_milli: Optional[float] = None


class WhoopWorkout(BaseModel):
    id: Optional[int] = None
    sport_id: Optional[int] = None
    sport_name: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    strain: Optional[float] = None
    average_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    kilojoule: Optional[float] = None
