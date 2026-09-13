"""Assembly of the brokerage holdings read model.

The one place that decides what a GET /api/v1/finance/holdings payload
looks like. Split out of the router so the router is left with HTTP
concerns only (auth, rate limit, envelope, status code), and so the
response is constructed exactly once rather than assembled field-by-field
by its caller.

The DB is reached through an injected `find_integration` callable rather
than an import of src.services.integrations.state. That inverts the
dependency -- this module states what it needs (user_id + slug -> row or
None) without naming who provides it -- and lets the route own the choice
of lookup, which is also the seam the endpoint tests substitute.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, cast, get_args

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...schemas.finance import (
    BrokerHoldings,
    BrokerStatus,
    FinanceHoldingsResponse,
)
from . import brokers, parsers

_log = logging.getLogger(__name__)

# Derived from the schema's Literal rather than hand-duplicated -- keeping
# the two in sync by comment alone is unenforceable drift risk; get_args()
# makes them structurally incapable of diverging.
VALID_STATUSES: tuple[BrokerStatus, ...] = get_args(BrokerStatus)


# Looks up one user's Integration row for a slug, or None. Structurally
# satisfied by src.services.integrations.state.find_integration and by any
# plain async def a test passes in.
Finder = Callable[[str, str, AsyncSession], Awaitable[Integration | None]]


def resolve_status(raw_status: object, *, slug: str | None = None) -> BrokerStatus:
    """Coerce Integration.status to the wire enum.

    An unexpected value becomes "error" rather than being handed to
    Pydantic, which would raise -- and a 500 would violate this endpoint's
    always-200 contract over a column this feature does not own.

    Silent to the user by design, but not to the operator: an
    Integration.status value outside the wire enum means either DB drift
    (a status this feature doesn't know about was written elsewhere) or a
    genuine bug, and coercing it to "error" with zero signal would hide
    that from Sentry/logs forever, indistinguishable from a normal
    provider failure.
    """
    if raw_status in VALID_STATUSES:
        return cast(BrokerStatus, raw_status)
    _log.warning(
        "Unexpected Integration.status %r for broker %r -- coercing to 'error'",
        raw_status,
        slug,
    )
    return "error"


def _safe_error_message(status: BrokerStatus, display_name: str) -> str | None:
    """Human-safe copy for the wire — never the raw Integration.last_error.

    The raw exception text (class name, upstream URL, status code) stays in
    the DB and is logged server-side at write time by
    integrations/personal/_oauth_base.record_sync_failure; per
    .claude/rules/api.md it must never reach the client.
    """
    if status == "expired":
        return f"Your {display_name} session expired. Reconnect to refresh holdings."
    if status == "error":
        return f"Couldn't reach {display_name}. Try syncing again."
    return None


def build_broker_block(integration: Integration, display_name: str) -> BrokerHoldings:
    """Project one Integration row into the wire shape.

    Pure given the row: every malformed-config case is absorbed by
    parsers.py, and nothing here performs I/O.
    """
    config = parsers.as_config(integration.config, slug=integration.slug)
    holdings = parsers.parse_holdings(config, slug=integration.slug)
    holding_count = parsers.resolve_holding_count(
        config, len(holdings), slug=integration.slug
    )
    status = resolve_status(integration.status, slug=integration.slug)

    return BrokerHoldings(
        broker=integration.slug,
        display_name=display_name,
        status=status,
        needs_reauth=status == "expired",
        currency=brokers.CURRENCY,
        holding_count=holding_count,
        truncated=holding_count > len(holdings),
        holdings=holdings,
        last_synced_at=parsers.iso_utc(integration.last_synced_at),
        error=_safe_error_message(status, display_name),
    )


def _error_block(slug: str) -> BrokerHoldings:
    """A synthetic error card for a broker whose lookup itself failed.

    Used only when `find_integration` raises -- there is no Integration row
    to project, so this does not go through build_broker_block. No details
    from the exception are included: per .claude/rules/api.md this must
    never carry a stack trace or internal error text to the client, even
    though the failure is already logged server-side by the caller.

    It still carries the same generic `error` copy as any other failed
    broker. Leaving it None rendered an empty card with no message at all --
    indistinguishable from a genuinely empty portfolio, so a DB outage
    looked to the user like "you own nothing".
    """
    display_name = brokers.display_name_for(slug)
    return BrokerHoldings(
        broker=slug,
        display_name=display_name,
        status="error",
        needs_reauth=False,
        currency=brokers.CURRENCY,
        holding_count=0,
        truncated=False,
        holdings=[],
        last_synced_at=None,
        error=_safe_error_message("error", display_name),
    )


async def collect_broker_holdings(
    user_id: str,
    db: AsyncSession,
    *,
    find_integration: Finder,
) -> FinanceHoldingsResponse:
    """Every connected brokerage for `user_id`, in catalogue order.

    A slug with no row is skipped rather than emitted as a disconnected
    placeholder -- `connected` is derived from whether anything survived
    the loop, which is what the frontend's empty state keys off.

    Two indexed point lookups (uq_integrations_user_slug) against a tiny
    result set; there is nothing to batch that would pay for itself.

    Each lookup is isolated so a transient DB failure on one slug (dropped
    connection, statement timeout) degrades that broker's card to "error"
    instead of 500-ing the whole response and taking the other, healthy
    broker down with it -- see the always-200 contract in api/v1/finance.py.
    SQLAlchemyError specifically, not a bare `except Exception`, so a bug in
    build_broker_block/parsers.py still fails loudly.
    """
    found: list[BrokerHoldings] = []
    for slug in brokers.BROKER_SLUGS:
        try:
            integration = await find_integration(user_id, slug, db)
        except SQLAlchemyError:
            _log.exception(
                "Integration lookup failed for user=%s slug=%s", user_id, slug
            )
            found.append(_error_block(slug))
            continue
        if integration is None:
            continue
        found.append(build_broker_block(integration, brokers.display_name_for(slug)))

    return FinanceHoldingsResponse(connected=len(found) > 0, brokers=found)
