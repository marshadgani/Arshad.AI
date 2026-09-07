"""Generic integration-record lifecycle: lookup, error classification, and
the status transitions that follow a fetch attempt.

Lifted verbatim from src/services/whoop/state.py and parameterised by slug
and reauth_codes so a second provider (Shopify) can share it instead of
re-deriving the same rules. Behaviour for Whoop is unchanged — whoop/state.py
now re-exports these functions bound to its own slug/reauth set.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...integrations.base import IntegrationError
from ...models.integration import Integration

_log = logging.getLogger(__name__)

# Statuses that still represent "the user has connected this provider".
#   connected — the normal path.
#   expired   — connected, but the token needs a refresh the user must
#               re-approve. Included so the pre-fetch gate can emit
#               needs_reauth instead of a "not connected" lie.
#   error     — included for self-healing. A transient upstream 5xx sets
#               this via apply_error_status; without it here, one bad
#               request would permanently blank the dashboard. mark_healthy
#               resets it on the next successful fetch.
# 'disconnected' and 'coming_soon' are excluded.
ACTIVE_STATUSES = ("connected", "expired", "error")

UPSTREAM_FALLBACK_STATUS = 502

_LAST_ERROR_MAX_CHARS = 500


async def find_integration(
    user_id: str, slug: str, db: AsyncSession
) -> Integration | None:
    """The user's integration for `slug`, if it is in any active status.

    No str() cast on user_id — verbatim lift of whoop/state.py:62's
    comparison. SQLAlchemy adapts the comparison against the UUID column;
    casting here would be a behaviour change, not a preservation of one.
    """
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.slug == slug,
            Integration.status.in_(ACTIVE_STATUSES),
        )
    )
    return result.scalar_one_or_none()


def classify_error(exc: Exception, reauth_codes: frozenset[str]) -> tuple[bool, int]:
    """Decide whether re-authentication is required, and the HTTP status to
    fall back to when it is not. Returns (needs_reauth, fallback_status).

    Pure: no I/O, no mutation, no Integration or session argument.

    Ordering is load-bearing. `.response` is only ever accessed inside the
    `isinstance(exc, httpx.HTTPStatusError)` branch. `httpx.RequestError`
    (ConnectTimeout, ReadTimeout, ConnectError, ...) is a sibling of
    HTTPStatusError under httpx.HTTPError and has NO `.response` attribute —
    touching it there would raise AttributeError while handling the
    original exception.
    """
    if isinstance(exc, IntegrationError):
        if exc.code in reauth_codes:
            return True, 0
        return False, UPSTREAM_FALLBACK_STATUS

    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 403):
            return True, 0
        return False, UPSTREAM_FALLBACK_STATUS

    if isinstance(exc, httpx.RequestError):
        return False, UPSTREAM_FALLBACK_STATUS

    return False, UPSTREAM_FALLBACK_STATUS


async def apply_error_status(
    integration: Integration, exc: Exception, needs_reauth: bool, db: AsyncSession
) -> None:
    """Impure counterpart to classify_error — persist the implied status.

    Never raises: a failure to record status must not turn a 502/409 into
    an unrelated 500.
    """
    try:
        integration.status = "expired" if needs_reauth else "error"
        integration.last_error = f"{type(exc).__name__}: {exc}"[:_LAST_ERROR_MAX_CHARS]
        await db.commit()
    except Exception:  # noqa: BLE001
        _log.exception(
            "Failed to persist integration error status for slug=%s", integration.slug
        )


async def mark_healthy(integration: Integration, db: AsyncSession) -> None:
    """Reset a prior error/expired status to connected after a successful
    fetch (self-healing).

    Guarded so a steady poll on an already-healthy integration does not
    issue a DB write on every single request.
    """
    if integration.status != "connected" or integration.last_error is not None:
        integration.status = "connected"
        integration.last_error = None
        await db.commit()
