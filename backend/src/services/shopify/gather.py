"""Concurrent Shopify fetch orchestration and result-processing primitives.

Separates the gather/throttle-fallback logic from both the route handler
and the domain-service modules (inventory_cover, service_debt, discount).
No FastAPI import. No database I/O beyond the state helpers.

Business constants are defined here so route handlers and domain services
can reference them without reaching into the HTTP layer or each other.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...integrations.base import IntegrationError
from ...models.integration import Integration
from .state import apply_error_status, classify_error

_log = logging.getLogger(__name__)

# ── Business constants ───────────────────────────────────────────────────────
# Defined here rather than in the route so domain services can reference them
# without touching the HTTP layer, and tests can pin them independently.

VELOCITY_WINDOW_DAYS = 30
TRAVEL_LOOKAHEAD_DAYS = 90
# Shopify's read_orders scope only exposes the last 60 days to non-Plus apps.
SERVICE_DEBT_ORDER_DAYS = 60

# Upstream failures absorbed into degraded 200 responses.
# ValueError also covers json.JSONDecodeError from resp.json() in client.py —
# a malformed Shopify body must never crash the always-200 endpoints.
FETCH_ERRORS: tuple[type[BaseException], ...] = (
    httpx.HTTPError,
    IntegrationError,
    ValueError,
)


def is_fetch_error(result: object) -> bool:
    return isinstance(result, FETCH_ERRORS)


def reraise_unexpected(result: object) -> None:
    """Gather runs with return_exceptions=True; anything that is not a known
    upstream failure is a programming error and must surface, not be silently
    recorded as a partial_failures flag."""
    if isinstance(result, BaseException) and not is_fetch_error(result):
        raise result


def gather_result(result: Any, alias: str, failures: list[str]) -> dict | None:
    """One Shopify gather result → its payload, or None with the reason
    recorded in `failures`."""
    reraise_unexpected(result)
    if is_fetch_error(result):
        _log.warning("Shopify %s fetch failed: %s", alias, result)
        failures.append(alias)
        return None
    if result.get("throttled"):
        if "throttled" not in failures:
            failures.append("throttled")
        return None
    failures.extend(
        f for f in result.get("partial_failures") or [] if f not in failures
    )
    return result


async def reauth_if_needed(
    integration: Integration, results: list[Any], db: AsyncSession
) -> bool:
    """Return True and persist the 'expired' status when any result from a
    Shopify gather indicates the token was revoked or cannot be refreshed."""
    for result in results:
        if is_fetch_error(result):
            needs_reauth, _ = classify_error(result)
            if needs_reauth:
                await apply_error_status(integration, result, True, db)
                return True
    return False


async def gather_shopify_pair(
    first: Any,
    second: Any,
    extra: Any | None = None,
) -> list[Any]:
    """Run two Shopify queries (plus an optional non-Shopify call) at once,
    falling back to serial for any that came back THROTTLED.

    Leaky-bucket cost: the variant page is roughly VARIANTS_PAGE_LIMIT (250)
    points and the orders page up to ~600 against a 50 points/s refill, so on
    an active store the pair can exceed the bucket and the second query
    comes back THROTTLED. That is the expected degradation path, not an error:
    the throttled query is re-run alone with max_retries=0 (each query already
    used its one retry inside the gather, so retries do not stack). A query
    still throttled after that is reported as 'throttled'.

    `first` and `second` must be callables that accept `max_retries` as a
    keyword argument (all execute_*_query functions in client.py do). `extra`
    is treated as a fire-and-forget non-Shopify call and is never retried.
    """
    calls = [first, second]
    if extra is not None:
        calls.append(extra)
    results = list(await asyncio.gather(*(c() for c in calls), return_exceptions=True))
    for i in (0, 1):
        if isinstance(results[i], dict) and results[i].get("throttled"):
            try:
                results[i] = await calls[i](max_retries=0)
            except FETCH_ERRORS as exc:
                results[i] = exc
    return results
