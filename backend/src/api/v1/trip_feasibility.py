"""POST /api/v1/trip-feasibility — go / no-go / unknown for a travel window.

Same always-200 contract as the Shopify intelligence routes (see
.claude/rules/api.md "Documented deviation"): provider state lives in body
flags, because a 401 would trigger the frontend's app-wide logout. Only a
malformed body (422) and the rate limit (429) are non-200.

Responses are never cached: they depend on the requested window and must
never show stale or degraded data as current.

The `_`-prefixed wrappers are the same monkeypatch seam used by
src/api/v1/shopify.py.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from functools import partial
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import Integration
from src.models.user import User
from src.schemas.shopify import TripFeasibilityRequest, TripFeasibilityResponse
from src.services.shopify import (
    client,
    gather,
    providers,
    state,
    tokens,
    trip_feasibility,
)

router = APIRouter(prefix="/api/v1/trip-feasibility", tags=["trip-feasibility"])

_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 60

_log = logging.getLogger(__name__)


# ── Collaborator seams (monkeypatchable module globals) ──────────────────


async def _check_rate_limit(user_id: str) -> None:
    await enforce_rate_limit(
        bucket="trip_feasibility",
        identity=user_id,
        limit=_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
        message=f"Too many requests. Retry after {_RATE_WINDOW_SECONDS} seconds.",
    )


async def _find_integration(user_id: str, db: AsyncSession) -> Integration | None:
    return await state.find_integration(user_id, db)


async def _get_token(integration: Integration, db: AsyncSession) -> str:
    return await tokens.get_access_token(integration, db)


async def _execute_variants_query(shop: str, token: str, **kwargs: Any) -> dict:
    return await client.execute_variant_inventory_query(shop, token, **kwargs)


async def _execute_orders_query(
    shop: str, token: str, since_iso: str, **kwargs: Any
) -> dict:
    return await client.execute_orders_query(shop, token, since_iso, **kwargs)


async def _list_calendar_events(
    db: AsyncSession, user: User, time_min: str, time_max: str
) -> dict | None:
    return await providers.list_calendar_events(db, user, time_min, time_max)


def _classify_error(exc: Exception) -> tuple[bool, int]:
    return state.classify_error(exc)


async def _apply_error_status(
    integration: Integration, exc: Exception, needs_reauth: bool, db: AsyncSession
) -> None:
    await state.apply_error_status(integration, exc, needs_reauth, db)


async def _mark_healthy(integration: Integration, db: AsyncSession) -> None:
    await state.mark_healthy(integration, db)


# ── Calendar helpers ──────────────────────────────────────────────────────


def _calendar_time_bounds(
    start_date: date, end_date: date
) -> tuple[str, str]:
    """ISO strings bracketing the travel window with one day of margin each side.

    The extra margin ensures a timed event near a boundary is fetched; the
    service layer performs the precise overlap test.
    """
    time_min = datetime.combine(
        start_date - timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    time_max = datetime.combine(
        end_date + timedelta(days=2), time.min, tzinfo=timezone.utc
    )
    return time_min.isoformat(), time_max.isoformat()


async def _resolve_calendar(calendar_call: Any) -> providers.CalendarResult:
    """Invoke `calendar_call`, absorb expected exceptions, parse the result.

    Extracted from the route handler so the same three lines are not
    duplicated across every early-exit path.
    """
    try:
        raw: Any = await calendar_call()
    except Exception as exc:
        raw = exc
    return providers.parse_calendar_result(raw)


# ── Route ────────────────────────────────────────────────────────────────


def _ok(model: TripFeasibilityResponse) -> JSONResponse:
    return JSONResponse({"data": model.model_dump()})


def _verdict(
    *,
    as_of: datetime,
    body: TripFeasibilityRequest,
    cal: providers.CalendarResult,
    shopify_connected: bool,
    shopify_needs_reauth: bool = False,
    variants: dict | None = None,
    orders: dict | None = None,
    failures: list[str] | None = None,
) -> JSONResponse:
    return _ok(
        trip_feasibility.check_trip_feasibility(
            as_of=as_of,
            start_date=body.start_date,
            end_date=body.end_date,
            variants_data=variants,
            orders_data=orders,
            cal=cal,
            shopify_connected=shopify_connected,
            shopify_needs_reauth=shopify_needs_reauth,
            window_days=gather.VELOCITY_WINDOW_DAYS,
            partial_failures=failures or [],
        )
    )


@router.post("")
async def check_trip_feasibility(
    body: TripFeasibilityRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Go / no-go / unknown for [start_date, end_date] (inclusive): projected
    Shopify stockouts in the window or the 7 days after, and timed Google
    Calendar events overlapping it. Always 200 except 422 / 429.
    """
    user_id = str(current_user.id)
    await _check_rate_limit(user_id)
    as_of = datetime.now(timezone.utc)

    cal_time_min, cal_time_max = _calendar_time_bounds(body.start_date, body.end_date)
    calendar_call = partial(
        _list_calendar_events,
        db,
        current_user,
        cal_time_min,
        cal_time_max,
    )

    integration = await _find_integration(user_id, db)
    if not integration:
        return _verdict(
            as_of=as_of,
            body=body,
            cal=await _resolve_calendar(calendar_call),
            shopify_connected=False,
        )
    if integration.status == "expired":
        return _verdict(
            as_of=as_of,
            body=body,
            cal=await _resolve_calendar(calendar_call),
            shopify_connected=True,
            shopify_needs_reauth=True,
        )

    try:
        ctx = state.shop_context(integration)
        token = await _get_token(integration, db)
    except gather.FETCH_ERRORS as exc:
        needs_reauth, _ = _classify_error(exc)
        _log.warning(
            "Trip-feasibility Shopify setup failed (needs_reauth=%s): %s",
            needs_reauth,
            gather.describe_error(exc),
        )
        await _apply_error_status(integration, exc, needs_reauth, db)
        return _verdict(
            as_of=as_of,
            body=body,
            cal=await _resolve_calendar(calendar_call),
            shopify_connected=True,
            shopify_needs_reauth=needs_reauth,
            failures=[] if needs_reauth else ["shopify"],
        )

    since_iso = (as_of - timedelta(days=gather.VELOCITY_WINDOW_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    variants_result, orders_result, calendar_result = await gather.gather_shopify_pair(
        partial(_execute_variants_query, ctx.shop, token),
        partial(_execute_orders_query, ctx.shop, token, since_iso),
        calendar_call,
    )
    cal = providers.parse_calendar_result(calendar_result)

    if await gather.reauth_if_needed(integration, [variants_result, orders_result], db):
        return _verdict(
            as_of=as_of,
            body=body,
            cal=cal,
            shopify_connected=True,
            shopify_needs_reauth=True,
        )

    failures: list[str] = []
    variants = gather.gather_result(
        variants_result, "variants", failures, root_field="productVariants"
    )
    orders = gather.gather_result(
        orders_result, "orders", failures, root_field="orders"
    )
    if variants is not None or orders is not None:
        await _mark_healthy(integration, db)
    return _verdict(
        as_of=as_of,
        body=body,
        cal=cal,
        shopify_connected=True,
        variants=variants,
        orders=orders,
        failures=failures,
    )
