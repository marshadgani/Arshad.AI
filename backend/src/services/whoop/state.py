"""Whoop integration-record lifecycle: lookup, error classification, and
the status transitions that follow a fetch attempt.

Separated from the router because this is where the subtle rules live —
which statuses still count as "connected", when a failure means re-auth
versus a transient upstream fault, and when to write back to Postgres. The
router should read as routing, not as a state machine.

Note the deliberate split between the pure classifier and the impure
persister: `classify_error` takes only the exception and returns a verdict,
so it is table-testable with no fixtures at all.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...integrations.base import IntegrationError
from ...models.integration import Integration

_log = logging.getLogger(__name__)

WHOOP_SLUG = "whoop"

# IntegrationError codes raised by the OAuth token layer that mean the user
# must re-approve access — no amount of retrying will fix them.
REAUTH_CODES = frozenset(
    {
        "refresh_failed",
        "no_refresh_token",
        "not_connected",
        "token_decryption_failed",
    }
)

# Statuses that still represent "the user has connected Whoop".
#   connected — the normal path.
#   expired   — the account IS connected but the token needs a refresh the
#               user must re-approve. Included so the pre-fetch gate can
#               emit needs_reauth instead of a 404 "not connected", which
#               would be a lie.
#   error     — included for self-healing. A transient Whoop 5xx sets this
#               via apply_error_status; without it here, one bad request
#               would permanently blank the dashboard. mark_healthy resets
#               it on the next successful fetch.
# 'disconnected' and 'coming_soon' are excluded.
ACTIVE_STATUSES = ("connected", "expired", "error")

UPSTREAM_FALLBACK_STATUS = 502

_LAST_ERROR_MAX_CHARS = 500


async def find_integration(user_id: str, db: AsyncSession) -> Integration | None:
    """The user's Whoop integration, if it is in any active status."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.slug == WHOOP_SLUG,
            Integration.status.in_(ACTIVE_STATUSES),
        )
    )
    return result.scalar_one_or_none()


def classify_error(exc: Exception) -> tuple[bool, int]:
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
        if exc.code in REAUTH_CODES:
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
        _log.exception("Failed to persist Whoop integration error status")


async def mark_healthy(integration: Integration, db: AsyncSession) -> None:
    """Reset a prior error/expired status to connected after a successful
    fetch (self-healing).

    Guarded so the dashboard's steady 120s poll on an already-healthy
    integration does not issue a DB write on every single request.
    """
    if integration.status != "connected" or integration.last_error is not None:
        integration.status = "connected"
        integration.last_error = None
        await db.commit()


def profile_first_name(integration: Integration) -> str | None:
    """Whoop first name from the integration config.

    Profile metadata is nested under config['profile'] — written there by
    upsert_oauth_integration in integrations/_oauth_base.py — not a flat
    config key. Read in one place so that stays true at one call site.
    """
    config = integration.config or {}
    return (config.get("profile") or {}).get("first_name")
