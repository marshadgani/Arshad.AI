"""Pydantic schemas for Apple Health push-ingest endpoints.

Apple Health has no cloud API — HealthKit is on-device only. Data arrives
via a user-configured iOS Shortcut (or the "Health Auto Export" app) that
POSTs a JSON export to /api/v1/apple-health/ingest on a schedule the user
controls (e.g. hourly, or "when app closes").

None of these models are ever written to a database row. The ingest
endpoint parses into AppleHealthSnapshot, encrypts and caches it in Redis
with a TTL, and that's the full lifecycle — see api/v1/apple_health.py and
services/apple_health/.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import ClassVar, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

_log = logging.getLogger(__name__)

# Physiological plausibility bounds. Out-of-range values are coerced to
# None rather than rejecting the whole payload — one bad sensor reading
# should not silently drop the user's entire hourly push.
_BOUNDS: dict[str, tuple[float, float]] = {
    "resting_heart_rate": (20, 250),
    "heart_rate_variability_ms": (5, 500),
    "sleep_hours": (0, 24),
    "active_energy_kcal": (0, 10_000),
    "steps": (0, 200_000),
    "vo2_max": (0, 100),
}


def _parse_recorded_at(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt > datetime.now(timezone.utc):
        return None
    return dt


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
    recorded_at: Optional[datetime] = None

    model_config = ConfigDict(extra="ignore")

    _dropped_fields: list[str] = PrivateAttr(default_factory=list)

    @field_validator("recorded_at", mode="before")
    @classmethod
    def _coerce_recorded_at(cls, value: object) -> Optional[datetime]:
        return _parse_recorded_at(value)

    @model_validator(mode="after")
    def _clamp_biometric_bounds(self) -> "AppleHealthIngestPayload":
        # mode='after' runs once every field is already coerced to its
        # declared numeric type — Health Auto Export can emit numerics as
        # strings (e.g. "58"), and comparing "58" against an int bound in a
        # mode='before' validator would raise TypeError.
        dropped: list[str] = []
        for field_name, (lo, hi) in _BOUNDS.items():
            value = getattr(self, field_name)
            if value is None:
                continue
            try:
                in_range = lo <= float(value) <= hi
            except (TypeError, ValueError):
                in_range = False
            if in_range:
                continue
            setattr(self, field_name, None)
            dropped.append(field_name)
            _log.warning(
                "apple_health.ingest: field %s coerced to null "
                "(value outside plausibility range)",
                field_name,
            )
        self._dropped_fields = dropped
        return self

    @property
    def dropped_fields(self) -> list[str]:
        return self._dropped_fields


class AppleHealthSnapshot(BaseModel):
    """What the dashboard reads, and what the cache stores.

    Distinct from AppleHealthIngestPayload on purpose: the payload is the
    loose, defensive shape a third-party exporter sends, this is the strict
    shape the app serves. `from_ingest` is the one seam between them.
    """

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
    recorded_at: Optional[datetime] = None
    received_at: Optional[datetime] = None

    @classmethod
    def from_ingest(
        cls, payload: AppleHealthIngestPayload, *, received_at: datetime
    ) -> "AppleHealthSnapshot":
        """Build the served snapshot from a validated push.

        The router used to spell this mapping out field by field, which put
        the metric list in a third place (payload model, snapshot model, and
        the endpoint) — adding a metric meant remembering to touch all
        three, and forgetting the third silently dropped it from the
        dashboard while every test still passed. Spreading model_dump()
        makes the mapping impossible to get out of step: the payload's own
        declared fields define it.
        """
        return cls(connected=True, received_at=received_at, **payload.model_dump())

    # The only two fields that describe connection state; every other field
    # is a reading. Derived rather than hand-listed so a metric added to the
    # model above cannot silently escape the invariant below.
    _STATE_FIELDS: ClassVar[frozenset[str]] = frozenset({"connected", "stale"})

    @model_validator(mode="after")
    def _check_state_combination(self) -> "AppleHealthSnapshot":
        """connected/stale plus eight independent optional fields make far
        more states representable than the three the API actually emits
        (see api/v1/apple_health.py's three construction sites:
        connected=False; connected=True+stale=True placeholder;
        connected=True+stale=False with real values). Nothing else stops a
        future edit from handing the frontend connected=False with a resting
        heart rate attached, or stale=True next to numbers that are no
        longer the latest reading.
        """
        if not self.connected or self.stale:
            readings = sorted(
                name
                for name, value in self
                if value is not None and name not in self._STATE_FIELDS
            )
            if readings:
                raise ValueError(
                    f"{', '.join(readings)} must be null whenever the snapshot "
                    "is disconnected or stale — those states have no current "
                    "reading behind them."
                )
        return self
