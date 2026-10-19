"""Render API reads for the deploy verdict: deploy record, logs and metrics.

Every function takes the httpx client and explicit times. Failures are logged as
exception type and HTTP status only, never message text, URLs or keys.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
import weakref
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from .models import DeployRecord, LogRecord, MetricWindow, normalise_level

_RENDER_API = "https://api.render.com/v1"
_TIMEOUT_SECONDS = 5.0
_PAGE_SIZE = 100
_MAX_LOGS_PER_WINDOW = 500
_MAX_CONCURRENT_CALLS = 3
# One semaphore per event loop: a module-level Semaphore binds to the first loop
# that contends on it and raises RuntimeError on any other (tests, reloads).
_SEMAPHORES: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)

_METRIC_PATHS: dict[str, tuple[str, dict[str, str]]] = {
    "cpu": ("cpu", {}),
    "memory": ("memory", {}),
    "latency": ("http-latency", {"quantile": "0.95"}),
}

_log = logging.getLogger(__name__)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _SEMAPHORES.get(loop)
    if semaphore is None:
        semaphore = _SEMAPHORES[loop] = asyncio.Semaphore(_MAX_CONCURRENT_CALLS)
    return semaphore


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instant(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _status_of(exc: BaseException) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _note(what: str, exc: BaseException) -> None:
    _log.warning(
        "render %s failed: %s status=%s", what, type(exc).__name__, _status_of(exc)
    )


def _failure_code(exc: BaseException) -> str:
    status = _status_of(exc)
    if status == 401:
        return "needs_reauth"
    if status == 403:
        return "scope_insufficient"
    return "fetch_error"


async def _get(
    client: httpx.AsyncClient,
    path: str,
    api_key: str,
    params: dict[str, Any] | None = None,
) -> Any:
    async with _semaphore():
        resp = await asyncio.wait_for(
            client.get(
                f"{_RENDER_API}{path}",
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
            ),
            timeout=_TIMEOUT_SECONDS,
        )
    resp.raise_for_status()
    return resp.json()


async def fetch_deploy_record(
    service_id: str, deploy_id: str, api_key: str, client: httpx.AsyncClient
) -> DeployRecord | None:
    """None on 404. 401/403 and other failures raise for the caller to classify."""
    path = f"/services/{quote(service_id, safe='')}/deploys/{quote(deploy_id, safe='')}"
    try:
        body = await _get(client, path, api_key)
    except Exception as exc:
        if _status_of(exc) == 404:
            return None
        _note("deploy lookup", exc)
        raise
    deploy = body.get("deploy", body) if isinstance(body, dict) else None
    if not isinstance(deploy, dict) or "createdAt" not in deploy:
        raise ValueError("malformed deploy payload")
    finished = deploy.get("finishedAt")
    return DeployRecord(
        service_id=service_id,
        deploy_id=str(deploy.get("id") or deploy_id),
        created_at=_parse_instant(deploy["createdAt"]),
        finished_at=_parse_instant(finished) if finished else None,
        status=str(deploy.get("status") or "unknown"),
    )


def _label(entry: dict[str, Any], name: str) -> str | None:
    for label in entry.get("labels") or []:
        if isinstance(label, dict) and label.get("name") == name:
            value = label.get("value")
            return value if isinstance(value, str) else None
    return None


def _parse_log(entry: dict[str, Any]) -> LogRecord:
    # The level is read here, once, into a typed field. Nothing after this point
    # may turn a record into a bare string before it is classified.
    return LogRecord(
        timestamp=_parse_instant(entry["timestamp"]),
        level=normalise_level(_label(entry, "level")),
        message=str(entry.get("message") or "")[:200],
        resource_type=_label(entry, "type"),
    )


async def fetch_logs(
    service_id: str,
    owner_id: str | None,
    window_start: datetime,
    window_end: datetime,
    api_key: str,
    client: httpx.AsyncClient,
    max_results: int = _MAX_LOGS_PER_WINDOW,
) -> tuple[list[LogRecord], bool, str | None]:
    """(records, truncated, failure_code). All levels are fetched so the total
    sample count is known; the level of each record is kept."""
    if not owner_id:
        return [], False, "owner_unknown"
    records: list[LogRecord] = []
    start, end = _iso(window_start), _iso(window_end)
    has_more = False
    try:
        for _ in range(math.ceil(max_results / _PAGE_SIZE)):
            body = await _get(
                client,
                "/logs",
                api_key,
                {
                    "ownerId": owner_id,
                    "resource": service_id,
                    "startTime": start,
                    "endTime": end,
                    "direction": "forward",
                    "limit": _PAGE_SIZE,
                },
            )
            records.extend(_parse_log(e) for e in body.get("logs") or [])
            has_more = bool(body.get("hasMore"))
            if not has_more:
                break
            next_start, next_end = body.get("nextStartTime"), body.get("nextEndTime")
            if not next_start or not next_end:
                # No cursor: re-requesting would return the same page again and
                # double-count its errors. Stop and report truncation instead.
                _log.warning("render logs page missing next cursor")
                break
            start, end = next_start, next_end
    except Exception as exc:
        _note("logs fetch", exc)
        return [], False, _failure_code(exc)
    truncated = has_more or len(records) > max_results
    return records[:max_results], truncated, None


async def fetch_metric(
    service_id: str,
    window_start: datetime,
    window_end: datetime,
    metric_type: str,
    api_key: str,
    client: httpx.AsyncClient,
) -> MetricWindow:
    """Mean and spread of one metric over the window; fetch_failed on any error."""
    spec = _METRIC_PATHS.get(metric_type)
    if spec is None:
        return MetricWindow(fetch_failed=True, failure_code="fetch_error")
    path, extra = spec
    try:
        body = await _get(
            client,
            f"/metrics/{path}",
            api_key,
            {
                "resource": service_id,
                "startTime": _iso(window_start),
                "endTime": _iso(window_end),
                "resolutionSeconds": 60,
                **extra,
            },
        )
        values = [
            float(point["value"])
            for series in body
            for point in series.get("values") or []
            if isinstance(point.get("value"), (int, float))
        ]
    except Exception as exc:
        _note(f"{metric_type} metric fetch", exc)
        return MetricWindow(fetch_failed=True, failure_code=_failure_code(exc))
    if not values:
        return MetricWindow()
    return MetricWindow(
        mean=statistics.fmean(values),
        stddev=statistics.pstdev(values),
        sample_count=len(values),
    )
