"""Pydantic schemas for Apple Health push-ingest endpoints.

Apple Health has no cloud API — HealthKit is on-device only. Data arrives
via a user-configured iOS Shortcut (or the "Health Auto Export" app) that
POSTs a JSON export to /api/v1/apple-health/ingest on a schedule the user
controls (e.g. hourly, or "when app closes").

None of these models are ever written to a database row. The ingest
endpoint parses into AppleHealthSnapshot, caches it in Redis with a TTL,
and that's the full lifecycle — see api/v1/apple_health.py.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AppleHealthIngestPayload(BaseModel):
    """Shape POSTed by the Shortcut. Deliberately loose (`extra` fields are
    ignored, not rejected) — Health Auto Export's schema changes across
    app versions and a strict model would break silently on every update.
    """

    resting_heart_rate: Optional[float] = None
    heart_rate_variability_ms: Optional[float] = None
    sleep_hours: Optional[float] = None
    active_energy_kcal: Optional[float] = None
    steps: Optional[int] = None
    vo2_max: Optional[float] = None
    recorded_at: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class AppleHealthSnapshot(BaseModel):
    connected: bool
    stale: bool = Field(
        default=False,
        description="True once the cached snapshot has outlived its TTL "
        "window without a fresh ingest — the Shortcut has likely stopped "
        "running rather than the data being wrong.",
    )
    resting_heart_rate: Optional[float] = None
    heart_rate_variability_ms: Optional[float] = None
    sleep_hours: Optional[float] = None
    active_energy_kcal: Optional[float] = None
    steps: Optional[int] = None
    vo2_max: Optional[float] = None
    recorded_at: Optional[str] = None
    received_at: Optional[str] = None
