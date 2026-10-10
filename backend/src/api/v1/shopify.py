"""Shopify Admin API endpoints.

Single source of HTTP concerns for the Shopify integration: auth, rate
limiting, caching policy, error policy, and status codes. All domain logic
lives in src/services/shopify/:

  transport        client.py
  wire parsing     parsers.py
  response models  dashboard.py
  integration state state.py
  OAuth token      tokens.py
  Redis            cache.py
  concurrent fetch gather.py   ← new FEAT-125
  Calendar/Gmail   providers.py ← new FEAT-125
  days-of-cover    inventory_cover.py
  break-even check discount.py
  thread matching  service_debt.py

The thin module-level `_`-prefixed wrappers below are an intentional seam,
mirroring src/api/v1/whoop.py: routes call them as module globals, which
keeps every collaborator substitutable from a test via monkeypatch without
the router taking a constructor or a DI container.

Always returns HTTP 200 for the dashboard and intelligence endpoints — see
.claude/rules/api.md "Documented deviation" for why the dashboard tile
endpoints never return 4xx.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import Integration
from src.models.user import User
from src.schemas.shopify import (
    DiscountSimulatorRequest,
    DiscountSimulatorResponse,
    InventoryCoverResponse,
    ServiceDebtResponse,
    ShopifyDashboard,
)
from src.services.shopify import (
    cache,
    client,
    discount,
    gather,
    inventory_cover,
    parsers,
    providers,
    service_debt,
    state,
    tokens,
)
from src.services.shopify import dashboard as dashboards

router = APIRouter(prefix="/api/v1/shopify", tags=["shopify"])

_RATE_LIMIT = 30
_RATE_WINDOW_SECONDS = 60

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


async def _execute_variants_query(shop: str, token: str, **kwargs: Any) -> dict:
    return await client.execute_variant_inventory_query(shop, token, **kwargs)


async def _execute_orders_query(
    shop: str, token: str, since_iso: str, **kwargs: Any
) -> dict:
    return await client.execute_orders_query(shop, token, since_iso, **kwargs)


async def _execute_discount_query(
    shop: str, token: str, variant_id: str, **kwargs: Any
) -> dict:
    return await client.execute_discount_variant_query(
        shop, token, variant_id, **kwargs
    )


async def _list_calendar_events(
    db: AsyncSession, user: User, time_min: str, time_max: str
) -> dict | None:
    return await providers.list_calendar_events(db, user, time_min, time_max)


async def _list_gmail_threads(db: AsyncSession, user: User) -> dict | None:
    return await providers.list_gmail_threads(db, user)


async def _get_cached_intel(kind: str, user_id: str) -> dict | None:
    return await cache.get_cached_intelligence(kind, user_id)


async def _set_cached_intel(kind: str, user_id: str, data: dict) -> None:
    await cache.set_cached_intelligence(kind, user_id, data)


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


def _ok_model(model: BaseModel) -> JSONResponse:
    return JSONResponse({"data": model.model_dump()})


def _degraded(integration: Integration, *, needs_reauth: bool) -> JSONResponse:
    return _ok(dashboards.shell_dashboard(integration, needs_reauth=needs_reauth))


def _utc_stamp(moment: datetime) -> str:
    # No colons beyond the time part, matching parsers.day_window, so
    # Shopify's search syntax cannot mis-split on a "+00:00" offset.
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cacheable(failures: list[str]) -> bool:
    """A degraded response must not be cached: for the 120s TTL it would hide
    recovery from a transient Shopify/Gmail failure. Truncation is a stable
    property of the data, so it does not block caching."""
    return all(f == "calendar_truncated" for f in failures)


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

    _log.warning(
        "Shopify dashboard fetch failed (status=%s): %s",
        fallback_status,
        gather.describe_error(exc),
    )
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
    except gather.FETCH_ERRORS as exc:
        return await _failure_response(integration, exc, db)

    await _mark_healthy(integration, db)
    await _set_cached(str(integration.id), {**payload, "cached_at": now.isoformat()})
    return JSONResponse({"data": payload})


# ── Intelligence layer (FEAT-125) ────────────────────────────────────────
# Same always-200 contract as /dashboard: provider state lives in body flags.


@router.get("/inventory-cover")
async def get_inventory_cover(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Days of cover per tracked variant, with stockouts that land inside a
    multi-day all-day Google Calendar event escalated as alerts. Always 200.
    """
    user_id = str(current_user.id)
    await _check_rate_limit(user_id)
    integration = await _find_integration(user_id, db)
    if not integration:
        return _ok_model(InventoryCoverResponse(connected=False))
    if integration.status == "expired":
        return _ok_model(InventoryCoverResponse(connected=True, needs_reauth=True))

    cached = await _get_cached_intel("inventory-cover", user_id)
    if cached is not None:
        return JSONResponse({"data": cached})

    as_of = datetime.now(timezone.utc)
    since_iso = _utc_stamp(as_of - timedelta(days=gather.VELOCITY_WINDOW_DAYS))
    try:
        ctx = state.shop_context(integration)
        token = await _get_token(integration, db)
    except gather.FETCH_ERRORS as exc:
        needs_reauth, _ = _classify_error(exc)
        _log.warning(
            "Shopify inventory-cover setup failed (needs_reauth=%s): %s",
            needs_reauth,
            gather.describe_error(exc),
        )
        await _apply_error_status(integration, exc, needs_reauth, db)
        return _ok_model(
            InventoryCoverResponse(
                connected=True,
                needs_reauth=needs_reauth,
                partial_failures=[] if needs_reauth else ["shopify"],
            )
        )

    results = await gather.gather_shopify_pair(
        partial(_execute_variants_query, ctx.shop, token),
        partial(_execute_orders_query, ctx.shop, token, since_iso),
        partial(
            _list_calendar_events,
            db,
            current_user,
            as_of.isoformat(),
            (as_of + timedelta(days=gather.TRAVEL_LOOKAHEAD_DAYS)).isoformat(),
        ),
    )
    variants_result, orders_result, calendar_result = results

    if await gather.reauth_if_needed(integration, [variants_result, orders_result], db):
        return _ok_model(InventoryCoverResponse(connected=True, needs_reauth=True))

    failures: list[str] = []
    variants = gather.gather_result(
        variants_result, "variants", failures, root_field="productVariants"
    )
    orders = gather.gather_result(
        orders_result, "orders", failures, root_field="orders"
    )

    cal = providers.parse_calendar_result(calendar_result)
    failures.extend(f for f in cal.partial_failures if f not in failures)

    response = inventory_cover.build_inventory_cover(
        variants,
        orders,
        cal.events,
        as_of=as_of,
        window_days=gather.VELOCITY_WINDOW_DAYS,
        calendar_connected=cal.connected,
        calendar_needs_reauth=cal.needs_reauth,
        partial_failures=failures,
    )
    if variants is not None or orders is not None:
        await _mark_healthy(integration, db)
    payload = response.model_dump()
    if _cacheable(failures):
        await _set_cached_intel(
            "inventory-cover", user_id, {**payload, "cached_at": as_of.isoformat()}
        )
    return JSONResponse({"data": payload})


@router.post("/discount-simulator")
async def simulate_discount(
    body: DiscountSimulatorRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Would this discount percent still cover the variant's unit cost?
    Computed on demand and never cached: price and cost change at any time.
    Always 200 except 422 for a malformed request body.
    """
    user_id = str(current_user.id)
    await _check_rate_limit(user_id)
    integration = await _find_integration(user_id, db)
    if not integration:
        return _ok_model(DiscountSimulatorResponse(connected=False))
    if integration.status == "expired":
        return _ok_model(DiscountSimulatorResponse(needs_reauth=True))

    try:
        ctx = state.shop_context(integration)
        token = await _get_token(integration, db)
        raw = await _execute_discount_query(ctx.shop, token, body.variant_id)
    except gather.FETCH_ERRORS as exc:
        needs_reauth, _ = _classify_error(exc)
        _log.warning(
            "Shopify discount-simulator fetch failed (needs_reauth=%s): %s",
            needs_reauth,
            gather.describe_error(exc),
        )
        await _apply_error_status(integration, exc, needs_reauth, db)
        return _ok_model(
            DiscountSimulatorResponse(
                needs_reauth=needs_reauth,
                partial_failures=[] if needs_reauth else ["variant"],
            )
        )

    if raw.get("throttled"):
        return _ok_model(DiscountSimulatorResponse(partial_failures=["throttled"]))
    variant = raw.get("variant")
    if variant is None:
        # A GraphQL error (e.g. missing scope) also yields a null variant; it
        # is reported as a failure, not as "variant does not exist".
        failures = raw.get("partial_failures") or []
        if failures:
            return _ok_model(DiscountSimulatorResponse(partial_failures=failures))
        return _ok_model(
            DiscountSimulatorResponse(
                variant_found=False,
                reason="No variant with that ID exists in this store.",
            )
        )
    price, unit_cost = discount.parse_variant_pricing(variant)
    if price is None:
        _log.warning("Shopify variant returned no usable price: %s", body.variant_id)
        return _ok_model(DiscountSimulatorResponse(partial_failures=["variant"]))
    await _mark_healthy(integration, db)
    return _ok_model(
        discount.evaluate_discount(price, unit_cost, body.discount_percent)
    )


@router.get("/service-debt")
async def get_service_debt(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Inbox threads older than 24h that the user has not replied to, matched
    to Shopify orders by snippet text. Always 200.
    """
    user_id = str(current_user.id)
    await _check_rate_limit(user_id)
    cached = await _get_cached_intel("service-debt", user_id)
    if cached is not None:
        return JSONResponse({"data": cached})

    integration = await _find_integration(user_id, db)
    now = datetime.now(timezone.utc)
    since_iso = _utc_stamp(now - timedelta(days=gather.SERVICE_DEBT_ORDER_DAYS))
    failures: list[str] = []
    needs_reauth = False
    shopify_connected = integration is not None

    shopify_live = integration is not None and integration.status != "expired"
    if shopify_connected and not shopify_live:
        needs_reauth = True
        failures.append("shopify")

    # Shop context and token are resolved BEFORE the gather: the token lookup
    # reads (and may refresh and commit) through `db`, and Gmail uses the same
    # AsyncSession. An AsyncSession allows one operation at a time, so running
    # both concurrently raises InvalidRequestError and 500s the endpoint.
    orders_coro: Any = None
    orders_setup_error: BaseException | None = None
    if shopify_live:
        try:
            ctx = state.shop_context(integration)
            token = await _get_token(integration, db)
            orders_coro = _execute_orders_query(
                ctx.shop, token, since_iso, with_line_items=False
            )
        except gather.FETCH_ERRORS as exc:
            orders_setup_error = exc

    coroutines: list[Any] = [_list_gmail_threads(db, current_user)]
    if orders_coro is not None:
        coroutines.append(orders_coro)
    results = await asyncio.gather(*coroutines, return_exceptions=True)
    gmail_result = results[0]
    orders_result = (
        orders_setup_error
        if orders_setup_error is not None
        else (results[1] if orders_coro is not None else None)
    )

    gmail = providers.parse_gmail_result(gmail_result)
    if gmail.needs_reauth:
        needs_reauth = True
    failures.extend(f for f in gmail.partial_failures if f not in failures)

    orders: list[dict] = []
    orders_truncated = False
    if shopify_live:
        if await gather.reauth_if_needed(integration, [orders_result], db):
            needs_reauth = True
            failures.append("shopify")
        else:
            payload = gather.gather_result(
                orders_result, "orders", failures, root_field="orders"
            )
            if payload is not None:
                orders = payload.get("orders") or []
                orders_truncated = bool(payload.get("orders_has_next_page"))
                await _mark_healthy(integration, db)

    matched = service_debt.match_threads_to_orders(gmail.threads, orders)
    response = ServiceDebtResponse(
        gmail_connected=gmail.connected,
        shopify_connected=shopify_connected,
        needs_reauth=needs_reauth,
        threads=service_debt.rank_threads(matched),
        threads_truncated=gmail.threads_truncated,
        orders_truncated=orders_truncated,
        partial_failures=failures,
    )
    payload_out = response.model_dump()
    if _cacheable(failures) and not needs_reauth:
        await _set_cached_intel(
            "service-debt", user_id, {**payload_out, "cached_at": now.isoformat()}
        )
    return JSONResponse({"data": payload_out})
