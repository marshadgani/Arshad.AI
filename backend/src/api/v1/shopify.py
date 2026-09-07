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

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.integrations.base import IntegrationError
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import Integration
from src.models.user import User
from src.schemas.shopify import ShopifyDashboard
from src.services.shopify import cache, client, parsers, state, tokens
from src.services.shopify import dashboard as dashboards

router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])

_RATE_LIMIT = 30
_RATE_WINDOW_SECONDS = 60

# Upstream failures the endpoint absorbs into a degraded 200. ValueError
# also covers json.JSONDecodeError from resp.json() in client.py — Shopify
# returning a malformed/non-JSON body must not crash this endpoint into an
# uncaught 500 (see module docstring: this always returns 200).
_FETCH_ERRORS = (httpx.HTTPError, IntegrationError, ValueError)

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
    whoop.py::_persist_failure_needs_reauth, which serves the same role for
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
    except _FETCH_ERRORS as exc:
        return await _failure_response(integration, exc, db)

    await _mark_healthy(integration, db)

    payload = dashboards.build_dashboard(raw, ctx, as_of=day_end).model_dump()
    await _set_cached(str(integration.id), {**payload, "cached_at": now.isoformat()})
    return JSONResponse({"data": payload})
