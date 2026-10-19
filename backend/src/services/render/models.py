"""Typed structures for the Render per-deploy regression verdict.

`LogRecord.level` is a required, typed field. It is set when the Render payload
is parsed and read as an attribute by the classifier, so no step in between may
reduce a record to a plain string.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

LogLevel = Literal["error", "warning", "critical", "info", "debug", "unknown"]
Verdict = Literal["regression", "neutral", "improvement", "unknown"]

_KNOWN_LEVELS = {"error", "warning", "critical", "info", "debug"}
_LEVEL_ALIASES = {"err": "error", "warn": "warning", "fatal": "critical"}


def normalise_level(value: Any) -> LogLevel:
    """Map a raw level label to a LogLevel; anything unrecognised is "unknown"."""
    if not isinstance(value, str):
        return "unknown"
    lowered = value.strip().lower()
    lowered = _LEVEL_ALIASES.get(lowered, lowered)
    return lowered if lowered in _KNOWN_LEVELS else "unknown"  # type: ignore[return-value]


class LogRecord(BaseModel):
    timestamp: datetime
    level: LogLevel
    message: str
    resource_type: str | None = None

    @field_validator("level", mode="before")
    @classmethod
    def _coerce_level(cls, value: Any) -> LogLevel:
        return normalise_level(value)


class MetricWindow(BaseModel):
    mean: float | None = None
    stddev: float | None = None
    sample_count: int = 0
    fetch_failed: bool = False
    failure_code: str | None = None


class DeployRecord(BaseModel):
    service_id: str
    deploy_id: str
    created_at: datetime
    finished_at: datetime | None = None
    status: str


class DeployWindow(BaseModel):
    start: datetime
    end: datetime
    is_complete: bool


class RenderServiceSummary(BaseModel):
    id: str
    name: str | None = None
    latest_deploy_id: str | None = None
    latest_deploy_status: str | None = None


class RenderServicesSnapshotResponse(BaseModel):
    connected: bool
    needs_reauth: bool = False
    services: list[RenderServiceSummary] = Field(default_factory=list)


class RenderVerdictResponse(BaseModel):
    verdict: Verdict
    before_error_count: int = 0
    after_error_count: int = 0
    before_error_rate: float = 0.0
    after_error_rate: float = 0.0
    cpu_before_mean: float | None = None
    cpu_after_mean: float | None = None
    memory_before_mean: float | None = None
    memory_after_mean: float | None = None
    latency_before_mean: float | None = None
    latency_after_mean: float | None = None
    connected: bool
    needs_reauth: bool = False
    partial_failures: list[str] = Field(default_factory=list)
    log_truncated: bool = False

    @model_validator(mode="after")
    def _forbid_impossible_states(self) -> Self:
        if not self.connected and self.needs_reauth:
            raise ValueError("needs_reauth requires connected")
        if not self.connected and self.verdict != "unknown":
            raise ValueError("a disconnected response must be unknown")
        return self

    @classmethod
    def degraded(
        cls,
        *,
        connected: bool,
        needs_reauth: bool = False,
        partial_failures: list[str] | None = None,
    ) -> RenderVerdictResponse:
        return cls(
            verdict="unknown",
            connected=connected,
            needs_reauth=needs_reauth,
            partial_failures=partial_failures or [],
        )
