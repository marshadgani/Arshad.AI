"""Pure verdict logic for a Render deploy. No I/O, no clock reads."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from .models import (
    DeployWindow,
    LogRecord,
    MetricWindow,
    RenderVerdictResponse,
    Verdict,
)

# Confidence threshold: compared to len(before_logs) and len(after_logs), the
# total records in the window, NOT the error count. A clean service with zero
# errors but non-empty logs still produces a verdict. It is not a divide-by-zero
# guard: the rate divides by window seconds.
_MIN_LOG_SAMPLES = 2
_WINDOW_LENGTH_SECONDS = 3600
_REGRESSION_RATE_MULTIPLIER = 1.5

_ERROR_LEVELS = ("error", "critical")
_LEVELS = ("error", "warning", "critical", "info", "debug", "unknown")


def compute_windows(
    deploy_start: datetime, deploy_finish: datetime | None, as_of: datetime
) -> tuple[DeployWindow, DeployWindow] | None:
    """Equal-length windows: [start-L, start) and [finish, finish+L).

    None while the deploy has no finish time; a missing finish is never read as now.
    """
    if deploy_finish is None:
        return None
    length = timedelta(seconds=_WINDOW_LENGTH_SECONDS)
    before_end = deploy_start
    after_end = deploy_finish + length
    before = DeployWindow(
        start=before_end - length, end=before_end, is_complete=before_end <= as_of
    )
    after = DeployWindow(
        start=deploy_finish, end=after_end, is_complete=after_end <= as_of
    )
    return before, after


def classify_logs(records: Sequence[LogRecord]) -> dict[str, int]:
    """Counts per level, read from each record's `.level` attribute.

    Raises AttributeError for anything that is not a LogRecord, so a level
    dropped earlier in the pipeline fails loudly instead of counting as clean.
    """
    counts = dict.fromkeys(_LEVELS, 0)
    for record in records:
        counts[record.level] += 1
    return counts


def _error_count(records: Sequence[LogRecord]) -> int:
    counts = classify_logs(records)
    return sum(counts[level] for level in _ERROR_LEVELS)


def compute_error_rate(count: int, window_duration_seconds: float) -> float:
    """Errors per minute."""
    if window_duration_seconds <= 0:
        return 0.0
    return count / (window_duration_seconds / 60.0)


_BLOCKING_FAILURES = (
    "insufficient_log_samples_before",
    "insufficient_log_samples_after",
    "logs",
    "log_level_unavailable_before",
    "log_level_unavailable_after",
    "log_truncated_before",
    "log_truncated_after",
)


_METRIC_FAILURES = ("cpu", "memory", "latency")


def _lower(after: float | None, before: float | None) -> bool:
    return after is not None and before is not None and after < before


def classify_verdict(
    before_rate: float,
    after_rate: float,
    before_window: DeployWindow,
    after_window: DeployWindow,
    partial_failures: Sequence[str],
    cpu_before: float | None,
    cpu_after: float | None,
    latency_before: float | None,
    latency_after: float | None,
) -> Verdict:
    if not (before_window.is_complete and after_window.is_complete):
        return "unknown"
    if any(flag in partial_failures for flag in _BLOCKING_FAILURES):
        return "unknown"
    if after_rate > before_rate * _REGRESSION_RATE_MULTIPLIER:
        return "regression"
    # A failed metric source cannot support "no regression".
    if any(name in partial_failures for name in _METRIC_FAILURES):
        return "unknown"
    clear_drop = after_rate * _REGRESSION_RATE_MULTIPLIER < before_rate
    metrics_better = _lower(cpu_after, cpu_before) and _lower(
        latency_after, latency_before
    )
    if clear_drop or (after_rate < before_rate and metrics_better):
        return "improvement"
    return "neutral"


def compute_verdict_from_data(
    before_logs: Sequence[LogRecord],
    after_logs: Sequence[LogRecord],
    before_truncated: bool,
    after_truncated: bool,
    before_window: DeployWindow,
    after_window: DeployWindow,
    cpu_before: MetricWindow,
    cpu_after: MetricWindow,
    memory_before: MetricWindow,
    memory_after: MetricWindow,
    latency_before: MetricWindow,
    latency_after: MetricWindow,
    connected: bool,
    needs_reauth: bool,
    extra_failures: Sequence[str] = (),
) -> RenderVerdictResponse:
    if not connected:
        return RenderVerdictResponse.degraded(
            connected=False, needs_reauth=needs_reauth
        )

    failures = list(extra_failures)
    if not (before_window.is_complete and after_window.is_complete):
        failures.append("window_incomplete")
    if "logs" not in failures:
        if len(before_logs) < _MIN_LOG_SAMPLES:
            failures.append("insufficient_log_samples_before")
        if len(after_logs) < _MIN_LOG_SAMPLES:
            failures.append("insufficient_log_samples_after")
    for suffix, logs in (("before", before_logs), ("after", after_logs)):
        # Logs present but none carrying a readable level: zero errors would be
        # an artefact of the missing label, not evidence of a clean window.
        if logs and classify_logs(logs)["unknown"] == len(logs):
            failures.append(f"log_level_unavailable_{suffix}")
    if before_truncated:
        failures.append("log_truncated_before")
    if after_truncated:
        failures.append("log_truncated_after")
    for name, pair in (
        ("cpu", (cpu_before, cpu_after)),
        ("memory", (memory_before, memory_after)),
        ("latency", (latency_before, latency_after)),
    ):
        if any(m.fetch_failed for m in pair):
            failures.append(name)

    before_count = _error_count(before_logs)
    after_count = _error_count(after_logs)
    before_seconds = (before_window.end - before_window.start).total_seconds()
    after_seconds = (after_window.end - after_window.start).total_seconds()
    before_rate = compute_error_rate(before_count, before_seconds)
    after_rate = compute_error_rate(after_count, after_seconds)

    verdict = classify_verdict(
        before_rate,
        after_rate,
        before_window,
        after_window,
        failures,
        cpu_before.mean,
        cpu_after.mean,
        latency_before.mean,
        latency_after.mean,
    )
    if needs_reauth:
        verdict = "unknown"

    return RenderVerdictResponse(
        verdict=verdict,
        before_error_count=before_count,
        after_error_count=after_count,
        before_error_rate=before_rate,
        after_error_rate=after_rate,
        cpu_before_mean=cpu_before.mean,
        cpu_after_mean=cpu_after.mean,
        memory_before_mean=memory_before.mean,
        memory_after_mean=memory_after.mean,
        latency_before_mean=latency_before.mean,
        latency_after_mean=latency_after.mean,
        connected=True,
        needs_reauth=needs_reauth,
        partial_failures=failures,
        log_truncated=before_truncated or after_truncated,
    )
