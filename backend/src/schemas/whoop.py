"""Pydantic response schemas for Whoop health data endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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
    recovery: Optional[WhoopRecovery] = None
    sleep: Optional[WhoopSleep] = None
    strain: Optional[WhoopStrain] = None
    user_first_name: Optional[str] = None


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
