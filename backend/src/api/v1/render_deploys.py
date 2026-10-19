"""GET /api/v1/render/services/{service_id}/deploys/{deploy_id}/verdict.

Read-only regression verdict for one Render deploy: error-level log counts and
rates (plus CPU, memory and latency when available) in equal windows before and
after the deploy. Nothing is posted anywhere.

Same always-200 contract as the Shopify and trip-feasibility routes (see
.claude/rules/api.md "Documented deviation"): a Render outage or an expired key
is reported in the body (`connected`, `needs_reauth`, `partial_failures`), never
as a 401 or 500, because a 401 would log the user out of the app. Only a bad
service id (422) and the rate limit (429) are non-200.

In `partial_failures`, `scope_insufficient` is emitted only when the logs
endpoint answers 403. A failed metric adds the metric name (cpu, memory,
latency) instead.

The `_`-prefixed wrappers are monkeypatch seams, as in src/api/v1/shopify.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.errors import http_error
from src.auth.crypto import decrypt
from src.auth.dependencies import get_current_user
from src.integrations.project.render import _SERVICE_ID
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import ApiKeyCredential, Integration
from src.models.user import User
from src.schemas.render import RenderVerdictResponse
from src.services.integrations.project_scoping import find_infra_integrations
from src.services.render import client as render_client
from src.services.render import verdict as render_verdict
from src.services.render.models import (
    DeployRecord,
    LogRecord,
    MetricWindow,
    RenderServicesSnapshotResponse,
    RenderServiceSummary,
)

router = APIRouter(prefix="/api/v1/render", tags=["render"])

_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 60
_METRICS = ("cpu", "memory", "latency")
_NOT_LIVE_STATUSES = frozenset(
    {"build_failed", "update_failed", "pre_deploy_failed", "canceled"}
)

_log = logging.getLogger(__name__)

# ── Collaborator seams (monkeypatchable module globals) ──────────────────


async def _check_rate_limit(user_id: str) -> None:
    await enforce_rate_limit(
        bucket="render_verdict",
        identity=user_id,
        limit=_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
        message=f"Too many requests. Retry after {_RATE_WINDOW_SECONDS} seconds.",
    )


async def _find_render_integration(
    user_id: str, db: AsyncSession
) -> Integration | None:
    render, _supabase = await find_infra_integrations(user_id, db)
    return render


async def _get_api_key(integration: Integration, db: AsyncSession) -> str | None:
    """The decrypted key, or None when it is missing or unreadable."""
    encrypted_key = await db.scalar(
        select(ApiKeyCredential.encrypted_key).where(
            ApiKeyCredential.integration_id == integration.id
        )
    )
    if encrypted_key is None:
        return None
    try:
        return decrypt(encrypted_key)
    except Exception as exc:  # noqa: BLE001
        _log.warning("render key decrypt failed: %s", type(exc).__name__)
        return None


async def _fetch_deploy_record(
    service_id: str, deploy_id: str, api_key: str, http: httpx.AsyncClient
) -> DeployRecord | None:
    return await render_client.fetch_deploy_record(service_id, deploy_id, api_key, http)


async def _fetch_logs(
    service_id: str,
    owner_id: str | None,
    start: datetime,
    end: datetime,
    api_key: str,
    http: httpx.AsyncClient,
) -> tuple[list[LogRecord], bool, str | None]:
    return await render_client.fetch_logs(
        service_id, owner_id, start, end, api_key, http
    )


async def _fetch_metric(
    service_id: str,
    start: datetime,
    end: datetime,
    metric: str,
    api_key: str,
    http: httpx.AsyncClient,
) -> MetricWindow:
    return await render_client.fetch_metric(
        service_id, start, end, metric, api_key, http
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _ok(model: RenderVerdictResponse) -> JSONResponse:
    return JSONResponse({"data": model.model_dump()})


def _text(value: Any) -> str | None:
    """Return value when it is a str, otherwise None."""
    return value if isinstance(value, str) else None


def _snapshot_services(row: Integration | None) -> list[dict[str, Any]]:
    config = row.config if row is not None and isinstance(row.config, dict) else {}
    services = config.get("services")
    if not isinstance(services, list):
        if row is not None:
            _log.warning("render integration snapshot has no services list")
        return []
    return [s for s in services if isinstance(s, dict)]


def _unwrap(result: Any, fallback: Any) -> Any:
    """A gather result, with an unexpected exception replaced by `fallback`."""
    if isinstance(result, asyncio.CancelledError):
        raise result
    if isinstance(result, BaseException):
        _log.warning("render verdict step failed: %s", type(result).__name__)
        return fallback
    return result


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("/services", summary="Render services from the stored snapshot")
async def list_services(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Services and their latest deploy ids from the last sync. No Render call."""
    row = await _find_render_integration(str(user.id), db)

    # Snapshot JSON is written by the sync job; a malformed entry is skipped so
    # one bad row cannot turn this always-200 route into a validation 500.
    snapshot = RenderServicesSnapshotResponse(
        connected=row is not None,
        needs_reauth=row is not None and row.status == "expired",
        services=[
            RenderServiceSummary(
                id=s["id"],
                name=_text(s.get("name")),
                latest_deploy_id=_text(s.get("latest_deploy_id")),
                latest_deploy_status=_text(s.get("latest_deploy_status")),
            )
            for s in _snapshot_services(row)
            if isinstance(s.get("id"), str) and s["id"]
        ],
    )

    return JSONResponse({"data": snapshot.model_dump()})


@router.get(
    "/services/{service_id}/deploys/{deploy_id}/verdict",
    summary="Regression verdict for one Render deploy",
)
async def deploy_verdict(
    service_id: str,
    deploy_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    as_of = datetime.now(timezone.utc)
    if not _SERVICE_ID.fullmatch(service_id):
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_service_id",
            "Service ID must match pattern (srv|crn)-[a-zA-Z0-9]+",
        )
    await _check_rate_limit(str(user.id))

    row = await _find_render_integration(str(user.id), db)
    if row is None:
        return _ok(RenderVerdictResponse.degraded(connected=False))

    service = next(
        (s for s in _snapshot_services(row) if s.get("id") == service_id), None
    )
    if service is None:
        return _ok(
            RenderVerdictResponse.degraded(
                connected=True, partial_failures=["service_not_found"]
            )
        )
    owner_id = service.get("owner_id")
    owner_id = owner_id if isinstance(owner_id, str) and owner_id else None

    api_key = await _get_api_key(row, db)
    if api_key is None:
        return _ok(RenderVerdictResponse.degraded(connected=True, needs_reauth=True))

    # Reads are done: free the pooled connection before the slow Render calls.
    await db.rollback()

    async with httpx.AsyncClient(timeout=10.0) as http:
        try:
            deploy = await _fetch_deploy_record(service_id, deploy_id, api_key, http)
        except Exception as exc:  # noqa: BLE001 - always-200: degrade, never 500
            http_status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            _log.warning(
                "render deploy lookup failed: %s status=%s",
                type(exc).__name__,
                http_status,
            )
            return _ok(
                RenderVerdictResponse.degraded(
                    connected=True,
                    needs_reauth=http_status == 401,
                    partial_failures=["deploy_record"],
                )
            )
        if deploy is None:
            return _ok(
                RenderVerdictResponse.degraded(
                    connected=True, partial_failures=["deploy_record"]
                )
            )

        if deploy.status in _NOT_LIVE_STATUSES:
            # A deploy that never went live cannot have changed behaviour; its
            # windows would compare the old release with itself.
            return _ok(
                RenderVerdictResponse.degraded(
                    connected=True, partial_failures=["deploy_not_live"]
                )
            )

        windows = render_verdict.compute_windows(
            deploy.created_at, deploy.finished_at, as_of
        )
        if windows is None:
            return _ok(
                RenderVerdictResponse.degraded(
                    connected=True, partial_failures=["deploy_in_progress"]
                )
            )
        before, after = windows

        no_logs: tuple[list[LogRecord], bool, str | None] = ([], False, "fetch_error")
        failed_metric = MetricWindow(fetch_failed=True, failure_code="fetch_error")
        results = await asyncio.gather(
            _fetch_logs(service_id, owner_id, before.start, before.end, api_key, http),
            _fetch_logs(service_id, owner_id, after.start, after.end, api_key, http),
            *(
                _fetch_metric(service_id, w.start, w.end, metric, api_key, http)
                for metric in _METRICS
                for w in (before, after)
            ),
            return_exceptions=True,
        )

    before_logs, before_trunc, before_code = _unwrap(results[0], no_logs)
    after_logs, after_trunc, after_code = _unwrap(results[1], no_logs)
    metrics = [_unwrap(r, failed_metric) for r in results[2:]]

    log_codes = [c for c in (before_code, after_code) if c]
    needs_reauth = "needs_reauth" in log_codes or any(
        m.failure_code == "needs_reauth" for m in metrics
    )
    failures: list[str] = []
    if log_codes:
        failures.append("logs")
        failures.extend(c for c in dict.fromkeys(log_codes) if c != "needs_reauth")

    response = render_verdict.compute_verdict_from_data(
        before_logs,
        after_logs,
        before_trunc,
        after_trunc,
        before,
        after,
        cpu_before=metrics[0],
        cpu_after=metrics[1],
        memory_before=metrics[2],
        memory_after=metrics[3],
        latency_before=metrics[4],
        latency_after=metrics[5],
        connected=True,
        needs_reauth=needs_reauth,
        extra_failures=failures,
    )
    return _ok(response)
