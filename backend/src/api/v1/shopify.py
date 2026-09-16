"""Shopify Admin API dashboard endpoint.

Single GET /dashboard, always returns HTTP 200 — same documented deviation
as /api/v1/whoop/dashboard (see .claude/rules/api.md): this endpoint backs
an always-visible page tile, and frontend/src/hooks/useFetch.ts treats ANY
401 as an Arshad.AI session expiry and clears the JWT, which must never
happen because of an unrelated third-party integration.

Routing, caching policy and error policy only. Everything it coordinates
lives in src/services/shopify/: transport in client.py, wire parsing in
parsers.py, response assembly in dashboard.py, integration-state rules in
state.py, the OAuth-provider seam in tokens.py, Redis in cache.py.

The thin module-level `_`-prefixed wrappers below are an intentional seam,
mirroring src/api/v1/whoop.py: routes call them as module globals, which
keeps every collaborator substitutable from a test via monkeypatch without
the router taking a constructor or a DI container.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.errors import http_error
from src.auth.dependencies import get_current_user
from src.integrations.base import IntegrationError
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import Integration
from src.models.user import User
from src.schemas.shopify import ShopifyDashboard
from src.services.shopify import cache, client, parsers, state, tokens
from src.services.shopify import dashboard as dashboards
from src.services.shopify import insights as insights_service

router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])

_RATE_LIMIT = 30
_RATE_WINDOW_SECONDS = 60

# Upstream failures the endpoint absorbs into a degraded 200. ValueError
# also covers json.JSONDecodeError from resp.json() in client.py — Shopify
# returning a malformed/non-JSON body must not crash this endpoint into an
# uncaught 500 (see module docstring: this always returns 200).
_FETCH_ERRORS = (httpx.HTTPError, IntegrationError, ValueError)

# /insights is NOT the always-200 dashboard tile — it uses the same
# 404/409/503 semantics as /api/v1/whoop/hrv-trend, so a failure here never
# masquerades as "0 revenue" the way the dashboard's degraded 200 does.
# asyncio.TimeoutError is included because the route wraps the fetch in
# asyncio.wait_for as a hard ceiling on top of the client's own cooperative
# time budget.
_INSIGHTS_FETCH_ERRORS = (
    httpx.HTTPError,
    IntegrationError,
    ValueError,
    asyncio.TimeoutError,
)

# Real upper bound on the whole insights fetch, independent of
# client.INSIGHTS_TIME_BUDGET_SECONDS (which is only a cooperative,
# checked-between-pages deadline).
_INSIGHTS_HARD_TIMEOUT_SECONDS = 25.0

# The only `days` values /insights accepts — matches cache.INSIGHTS_DAY_VARIANTS
# and the frontend's 7/14/30 segmented control.
_INSIGHTS_DAY_OPTIONS = (7, 14, 30)

_log = logging.getLogger(__name__)


# ── Collaborator seams (monkeypatchable module globals) ──────────────────


async def _check_rate_limit(user_id: str) -> None:
    await enforce_rate_limit(
        bucket="shopify",
        identity=user_id,
        limit=_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
        message=f"Too many requests. Retry after {_RATE_WINDOW_SECONDS} seconds.",
    )


async def _find_integration(user_id: str, db: AsyncSession) -> Integration | None:
    return await state.find_integration(user_id, db)


async def _get_token(integration: Integration, db: AsyncSession) -> str:
    return await tokens.get_access_token(integration, db)


async def _get_cached(integration_id: str) -> dict | None:
    return await cache.get_cached_dashboard(integration_id)


async def _set_cached(integration_id: str, data: dict) -> None:
    await cache.set_cached_dashboard(integration_id, data)


async def _execute_query(shop: str, token: str, day_start: str, day_end: str) -> dict:
    return await client.execute_dashboard_query(shop, token, day_start, day_end)


def _classify_error(exc: Exception) -> tuple[bool, int]:
    return state.classify_error(exc)


async def _apply_error_status(
    integration: Integration, exc: Exception, needs_reauth: bool, db: AsyncSession
) -> None:
    await state.apply_error_status(integration, exc, needs_reauth, db)


async def _mark_healthy(integration: Integration, db: AsyncSession) -> None:
    await state.mark_healthy(integration, db)


async def _get_cached_insights(integration_id: str, days: int) -> dict | None:
    return await cache.get_cached_insights(integration_id, days)


async def _set_cached_insights(integration_id: str, days: int, data: dict) -> None:
    await cache.set_cached_insights(integration_id, days, data)


async def _execute_insights_query(
    shop: str, token: str, window_start: str, window_end: str
) -> dict:
    return await client.execute_insights_query(shop, token, window_start, window_end)


# ── Response helpers ─────────────────────────────────────────────────────


def _ok(dashboard: ShopifyDashboard) -> JSONResponse:
    return JSONResponse({"data": dashboard.model_dump()})


def _degraded(integration: Integration, *, needs_reauth: bool) -> JSONResponse:
    return _ok(dashboards.shell_dashboard(integration, needs_reauth=needs_reauth))


async def _failure_response(
    integration: Integration, exc: Exception, db: AsyncSession
) -> JSONResponse:
    """Classify a fetch failure, persist the implied status, and render the
    matching degraded 200.

    Collapses the classify/persist/branch block so error policy lives in one
    named place instead of inline in the happy path — mirrors
    whoop.py::_persist_fetch_failure, which serves the same role for
    the 409-raising Whoop routes.
    """
    needs_reauth, fallback_status = _classify_error(exc)
    await _apply_error_status(integration, exc, needs_reauth, db)
    if needs_reauth:
        return _degraded(integration, needs_reauth=True)

    _log.warning("Shopify dashboard fetch failed (status=%s): %s", fallback_status, exc)
    dashboard = dashboards.shell_dashboard(integration, needs_reauth=False)
    dashboard.partial_failures = ["dashboard"]
    return _ok(dashboard)


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Today's revenue, order count, low-stock SKUs, and a recent-orders
    feed. Always returns HTTP 200 — see module docstring.
    """
    await _check_rate_limit(str(current_user.id))
    integration = await _find_integration(str(current_user.id), db)
    if not integration:
        return _ok(ShopifyDashboard(connected=False))

    if integration.status == "expired":
        return _degraded(integration, needs_reauth=True)

    now = datetime.now(timezone.utc)
    try:
        ctx = state.shop_context(integration)
        day_start, day_end = parsers.day_window(ctx.timezone, now)

        cached = await _get_cached(str(integration.id))
        if cached is not None:
            return JSONResponse({"data": cached})

        token = await _get_token(integration, db)
        raw = await _execute_query(ctx.shop, token, day_start, day_end)
        # Parsing/validation runs inside the same guard as the fetch: a
        # malformed wire payload must degrade to the always-200 contract
        # this endpoint promises, not surface as an uncaught 500.
        payload = dashboards.build_dashboard(raw, ctx, as_of=day_end).model_dump()
    except _FETCH_ERRORS as exc:
        return await _failure_response(integration, exc, db)

    await _mark_healthy(integration, db)
    await _set_cached(str(integration.id), {**payload, "cached_at": now.isoformat()})
    return JSONResponse({"data": payload})


@router.get("/insights")
async def get_insights(
    days: int = Query(default=14),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """N-day revenue/order trend for the connected store.

    NOT the always-200 dashboard tile: answers honest 404/409/503, same
    semantics as /api/v1/whoop/hrv-trend. Never returns 401 — see module
    docstring on why a third-party token issue must never look like an
    Arshad.AI session expiry to frontend/src/hooks/useFetch.ts.

    `days` is checked against _INSIGHTS_DAY_OPTIONS rather than typed as
    Literal[7, 14, 30]: pydantic v2's Literal validator does not coerce a
    query string ("14") into the matching int member, so every valid
    request would 422. Bounding to exactly {7, 14, 30} here instead keeps
    Redis key cardinality at 3/integration (matching cache.INSIGHTS_DAY_VARIANTS)
    and matches the three options the frontend's segmented control offers.
    """
    if days not in _INSIGHTS_DAY_OPTIONS:
        raise http_error(
            422,
            "validation_error",
            "days must be one of 7, 14, or 30.",
            details={"allowed": list(_INSIGHTS_DAY_OPTIONS)},
        )

    await _check_rate_limit(str(current_user.id))

    integration = await _find_integration(str(current_user.id), db)
    if not integration:
        raise http_error(
            404,
            "shopify_not_connected",
            "No Shopify integration found for this account.",
        )

    if integration.status == "expired":
        raise http_error(
            409,
            "shopify_reauth_required",
            "Shopify access has expired. Reconnect your store.",
        )

    now = datetime.now(timezone.utc)

    cached = await _get_cached_insights(str(integration.id), days)
    if cached is not None:
        return JSONResponse({"data": cached})

    try:
        # Inside the guard: shop_context raises IntegrationError
        # ("shopify_shop_missing") on a record whose shop domain never
        # persisted, and state.REAUTH_CODES classifies that as reauth —
        # so it must reach the 409 branch below, not escape as a generic
        # 500 from main.py's catch-all handler.
        ctx = state.shop_context(integration)
        bounds = parsers.window_bounds(ctx.timezone, now, days)

        token = await _get_token(integration, db)
        # Release the implicit read transaction opened by the integration
        # lookup/token fetch above before the upstream network call — see
        # .claude/rules/database.md: never hold a transaction open across a
        # network call. SQLAlchemy lazily starts a fresh one for the
        # mark_healthy/apply_error_status write below.
        await db.rollback()

        raw = await asyncio.wait_for(
            _execute_insights_query(ctx.shop, token, bounds.start_iso, bounds.end_iso),
            timeout=_INSIGHTS_HARD_TIMEOUT_SECONDS,
        )
        # Parsing runs inside the same guard as the fetch: a malformed wire
        # payload must become a 503, never an uncaught 500.
        payload = insights_service.build_insights(raw, ctx, bounds, days).model_dump()
    except _INSIGHTS_FETCH_ERRORS as exc:
        needs_reauth, _fallback_status = _classify_error(exc)
        await _apply_error_status(integration, exc, needs_reauth, db)
        if needs_reauth:
            raise http_error(
                409,
                "shopify_reauth_required",
                "Shopify access has expired. Reconnect your store.",
            ) from exc
        _log.warning("Shopify insights fetch failed: %s", exc)
        raise http_error(
            503,
            "shopify_upstream_unavailable",
            "Shopify API is temporarily unavailable. Retry shortly.",
        ) from exc

    await _mark_healthy(integration, db)
    await _set_cached_insights(
        str(integration.id), days, {**payload, "cached_at": now.isoformat()}
    )
    return JSONResponse({"data": {**payload, "cached_at": now.isoformat()}})
