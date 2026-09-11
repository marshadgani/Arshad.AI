"""Whoop health data endpoints.

Fetches live data from the Whoop Developer API using the stored OAuth
token. All endpoints require the user to have connected their Whoop
account first.

Biometric values are read per request and returned straight to the caller;
nothing here writes recovery, sleep, strain, HRV or workout data to
Postgres. See the standing decision in
integrations/personal/oauth_providers.py.

This module is routing and wire shape only. The work it coordinates lives
in src/services/whoop/: transport in client.py, wire parsing in parsers.py,
integration-state rules in state.py, the OAuth-provider seam in tokens.py.

The thin module-level `_`-prefixed wrappers below are an intentional seam,
not indirection for its own sake: routes call them as module globals, which
keeps every collaborator substitutable from a test via monkeypatch without
the router taking a constructor or a DI container.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.errors import error_body, http_error
from src.auth.dependencies import get_current_user
from src.integrations.base import IntegrationError
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import Integration
from src.models.user import User
from src.schemas.whoop import WhoopDashboard
from src.services.whoop import client, parsers, state, tokens

router = APIRouter(prefix="/api/v1/whoop", tags=["whoop"])

# 30 requests/minute per user across every Whoop endpoint.
_RATE_LIMIT = 30
_RATE_WINDOW_SECONDS = 60

_UPSTREAM_ERROR_MESSAGE = (
    "Upstream health service is unavailable. Please try again later."
)

_WHOOP_REAUTH_ERROR = error_body(
    "whoop_reauth_required", "Whoop session expired. Please re-authenticate."
)
_WHOOP_NOT_CONNECTED_ERROR = error_body(
    "whoop_not_connected", "Whoop account not connected."
)


# ── Collaborator seams (monkeypatchable module globals) ──────────────────


async def _check_rate_limit(user_id: str) -> None:
    await enforce_rate_limit(
        bucket="whoop",
        identity=user_id,
        limit=_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
        message=f"Too many requests. Retry after {_RATE_WINDOW_SECONDS} seconds.",
    )


async def _find_whoop_integration(user_id: str, db: AsyncSession) -> Integration | None:
    return await state.find_integration(user_id, db)


async def _get_token(integration: Integration, db: AsyncSession) -> str:
    return await tokens.get_access_token(integration, db)


async def _whoop_get(
    path: str, access_token: str, params: dict[str, Any] | None = None
) -> Any:
    return await client.get(path, access_token, params)


async def _fetch_dashboard_data(token: str) -> tuple[Any, Any, Any]:
    return await client.fetch_dashboard_bodies(token)


def _classify_whoop_error(exc: Exception) -> tuple[bool, int]:
    return state.classify_error(exc)


async def _apply_whoop_error_status(
    integration: Integration, exc: Exception, needs_reauth: bool, db: AsyncSession
) -> None:
    await state.apply_error_status(integration, exc, needs_reauth, db)


async def _mark_whoop_healthy(integration: Integration, db: AsyncSession) -> None:
    await state.mark_healthy(integration, db)


# ── Shared request-flow helpers ──────────────────────────────────────────


async def _resolve_active_integration(user_id: str, db: AsyncSession) -> Integration:
    """Rate-limit, then resolve the integration for the two list endpoints.

    Returns 404 whoop_not_connected when there is no Whoop integration at
    all. Returns 409 whoop_reauth_required — a deliberate, documented
    deviation from the standard status table in .claude/rules/api.md — when
    the integration exists but the token is expired/revoked. 401 is avoided
    on purpose: frontend/src/hooks/useFetch.ts calls clearToken() on ANY
    401, which would log the user out of Arshad.AI itself over an unrelated
    third-party token expiring. 409 (conflict with current resource state)
    is returned instead, for both this pre-fetch gate and the mid-fetch
    exception path, so the two produce one consistent shape.
    """
    await _check_rate_limit(user_id)
    integration = await _find_whoop_integration(user_id, db)
    if not integration:
        raise HTTPException(status_code=404, detail=_WHOOP_NOT_CONNECTED_ERROR)
    if integration.status == "expired":
        raise HTTPException(status_code=409, detail=_WHOOP_REAUTH_ERROR)
    return integration


async def _persist_fetch_failure(
    integration: Integration, exc: Exception, db: AsyncSession
) -> None:
    """Persist the integration status a failed fetch implies, then raise
    unless the failure is a re-auth condition.

    Returning normally means "this is a re-auth failure, render your own
    shape for it" — the list endpoints answer 409 (see
    _resolve_active_integration). Anything else, a timeout or a Whoop 5xx,
    becomes the upstream error status here because no caller has a better
    answer for it.

    Collapses a block that was previously copy-pasted into all three
    routes, where the three copies had to be kept in step by hand.
    """
    needs_reauth, fallback_status = _classify_whoop_error(exc)
    await _apply_whoop_error_status(integration, exc, needs_reauth, db)
    if not needs_reauth:
        raise http_error(
            fallback_status, "whoop_api_error", _UPSTREAM_ERROR_MESSAGE
        ) from exc


async def _fetch_list_body(
    user_id: str, db: AsyncSession, path: str, params: dict[str, Any]
) -> Any:
    """The whole request flow the two list endpoints share, minus parsing.

    Resolve → token → fetch → persist-status, with the failure branch that
    turns any fetch error into 409 whoop_reauth_required. Both endpoints
    ran this same seven-line sequence verbatim; the only thing that ever
    differed between them is the path, the query params, and how the body
    is parsed. Keeping one copy means a change to the 404/409 wire contract
    (documented in _resolve_active_integration) is made once rather than
    made twice and hopefully kept in step.

    Returns the raw upstream body — parsing stays in the route, because
    that is the one part that is genuinely per-endpoint.
    """
    integration = await _resolve_active_integration(user_id, db)

    try:
        token = await _get_token(integration, db)
        body = await _whoop_get(path, token, params)
    except (httpx.HTTPError, IntegrationError) as exc:
        await _persist_fetch_failure(integration, exc, db)
        raise HTTPException(status_code=409, detail=_WHOOP_REAUTH_ERROR) from exc

    await _mark_whoop_healthy(integration, db)
    return body


def _list_response(items: list[dict[str, Any]]) -> JSONResponse:
    """The `{data, total}` collection envelope from .claude/rules/api.md."""
    return JSONResponse({"data": items, "total": len(items)})


def _dashboard_response(dashboard: WhoopDashboard) -> JSONResponse:
    """The `{data: ...}` single-resource envelope from .claude/rules/api.md."""
    return JSONResponse({"data": dashboard.model_dump()})


def _reauth_dashboard(integration: Integration) -> JSONResponse:
    """Token expired/revoked: connected, but carrying no readings."""
    return _dashboard_response(
        WhoopDashboard(
            connected=True,
            needs_reauth=True,
            user_first_name=state.profile_first_name(integration),
        )
    )


def _degraded_dashboard(integration: Integration) -> JSONResponse:
    """Transient upstream failure: the connection is fine, the fetch wasn't."""
    return _dashboard_response(
        WhoopDashboard(
            connected=True,
            degraded=True,
            user_first_name=state.profile_first_name(integration),
        )
    )


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return today's recovery, sleep, and strain snapshot.

    Always returns HTTP 200. When the Whoop token is expired/revoked, the
    response carries needs_reauth: true with null biometric fields instead
    of an error status — this endpoint backs the always-visible dashboard
    tile and a 4xx/5xx here would blank the whole Health & Fitness page for
    a condition the frontend can render gracefully. When a transient
    upstream failure occurs (network timeout, Whoop 5xx) the response
    carries degraded: true with null biometric fields, distinguishable from
    a genuine no-data-recorded-today response.
    """
    await _check_rate_limit(str(current_user.id))
    integration = await _find_whoop_integration(str(current_user.id), db)
    if not integration:
        return _dashboard_response(WhoopDashboard(connected=False))

    if integration.status == "expired":
        return _reauth_dashboard(integration)

    try:
        token = await _get_token(integration, db)
        recovery_body, sleep_body, strain_body = await _fetch_dashboard_data(token)
    except (httpx.HTTPError, IntegrationError) as exc:
        # Deliberately not _persist_fetch_failure: that raises for any
        # non-reauth failure, which would turn every timeout or Whoop 5xx
        # into a 502 on an endpoint documented and relied on as always-200.
        # Its two steps are called directly here and the fallback status
        # discarded — it must never reach the wire from /dashboard.
        needs_reauth, _fallback_status = _classify_whoop_error(exc)
        await _apply_whoop_error_status(integration, exc, needs_reauth, db)
        if needs_reauth:
            return _reauth_dashboard(integration)
        return _degraded_dashboard(integration)

    await _mark_whoop_healthy(integration, db)

    recovery_records = parsers.records_of(recovery_body)
    sleep_records = parsers.records_of(sleep_body)
    strain_records = parsers.records_of(strain_body)

    return _dashboard_response(
        WhoopDashboard(
            connected=True,
            recovery=(
                parsers.parse_recovery(recovery_records[0])
                if recovery_records
                else None
            ),
            sleep=parsers.parse_sleep(sleep_records[0]) if sleep_records else None,
            strain=parsers.parse_strain(strain_records[0]) if strain_records else None,
            user_first_name=state.profile_first_name(integration),
        )
    )


@router.get("/hrv-trend")
async def get_hrv_trend(
    days: int = Query(default=14, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return HRV data points for the last N days (max 30).

    404/409 wire shape is explained in _resolve_active_integration.
    """
    start = (date.today() - timedelta(days=days)).isoformat()
    body = await _fetch_list_body(
        str(current_user.id), db, client.RECOVERY_PATH, {"limit": days, "start": start}
    )
    return _list_response(
        [point.model_dump() for point in parsers.parse_hrv_trend(body)]
    )


@router.get("/workouts")
async def get_workouts(
    limit: int = Query(default=10, ge=1, le=25),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return recent workouts. Same 404/409 wire shape as /hrv-trend."""
    body = await _fetch_list_body(
        str(current_user.id), db, client.WORKOUT_PATH, {"limit": limit}
    )
    return _list_response(
        [
            parsers.parse_workout(record).model_dump()
            for record in parsers.records_of(body)
        ]
    )
