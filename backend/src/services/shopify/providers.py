"""External provider (Google Calendar, Gmail, Calendly) fetch and
result-parsing for the Shopify intelligence layer.

Centralises the ProviderNotLinked / ProviderReauthRequired / ToolError /
BaseException isinstance dispatch so neither the route handler nor any
domain-service module needs to perform that dance. Both routes that use
these providers (get_inventory_cover, get_service_debt) previously duplicated
the same isinstance chain; now they call parse_calendar_result /
parse_gmail_result and receive a typed dataclass.

Calendly is a personal API-key integration (read-only scheduled events).
`resolve_calendly` is the single entry point for the trip-checker: it loads
the stored token, calls the Calendly API, and returns a `CalendlyFetchResult`
with all failure states encoded as flags so the route stays always-200.

Client imports remain deferred (inside async function bodies): the Calendar
and Gmail client modules pull in the token service, which must not be
evaluated while the integrations package is still initialising — this is the
same constraint that motivated the deferred imports in the original route.
ProviderNotLinked / ProviderReauthRequired / ToolError come from tools.base,
which is safe to import at module level.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import decrypt
from ...models.integration import ApiKeyCredential, Integration
from ...models.user import User
from ...services.integrations.state import ACTIVE_STATUSES
from ...tools.base import ProviderNotLinked, ProviderReauthRequired, ToolError
from .gather import describe_error

_log = logging.getLogger(__name__)

GMAIL_UNANSWERED_QUERY = "in:inbox -from:me older_than:24h"
GMAIL_PAGE_SIZE = 100
CALENDAR_PAGE_SIZE = 250


@dataclass
class CalendarResult:
    """Structured outcome of a Calendar events fetch; never raises on provider
    errors — provider failures are encoded in the fields instead."""

    events: list[dict[str, Any]] = field(default_factory=list)
    connected: bool = True
    needs_reauth: bool = False
    calendar_truncated: bool = False
    partial_failures: list[str] = field(default_factory=list)


@dataclass
class GmailResult:
    """Structured outcome of a Gmail threads.list call; never raises on provider
    errors — provider failures are encoded in the fields instead."""

    threads: list[dict[str, Any]] = field(default_factory=list)
    connected: bool = True
    needs_reauth: bool = False
    threads_truncated: bool = False
    partial_failures: list[str] = field(default_factory=list)


async def list_calendar_events(
    db: AsyncSession,
    user: User,
    time_min: str,
    time_max: str,
) -> dict | None:
    """Raw Calendar events response — suitable as a gather() coroutine.

    Callers pass the result to parse_calendar_result; they never inspect it
    directly.
    """
    from src.tools.clients import google_calendar  # deferred: see module docstring

    return await google_calendar.request(
        db=db,
        user=user,
        method="GET",
        path="calendars/primary/events",
        params={
            "singleEvents": "true",
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": CALENDAR_PAGE_SIZE,
            "orderBy": "startTime",
            "fields": (
                "nextPageToken,items(status,summary,"
                "start(date,dateTime),end(date,dateTime))"
            ),
        },
    )


async def list_gmail_threads(db: AsyncSession, user: User) -> dict | None:
    """Raw Gmail threads response — suitable as a gather() coroutine.

    Fetches only threads older than 24 hours that contain no message sent by
    the user (`GMAIL_UNANSWERED_QUERY`). Callers pass the result to
    parse_gmail_result; they never inspect it directly.
    """
    from src.tools.clients import gmail  # deferred: see module docstring

    return await gmail.request(
        db=db,
        user=user,
        method="GET",
        path="users/me/threads",
        params={
            "q": GMAIL_UNANSWERED_QUERY,
            "maxResults": GMAIL_PAGE_SIZE,
            "fields": "nextPageToken,threads(id,snippet)",
        },
    )


def parse_calendar_result(result: Any) -> CalendarResult:
    """Dispatch a raw gather() result to a CalendarResult.

    ProviderNotLinked and ProviderReauthRequired both subclass ToolError, so
    the specific types are tested first — the generic ToolError branch would
    otherwise swallow them and incorrectly treat reauth as a transient error.
    """
    if isinstance(result, ProviderNotLinked):
        return CalendarResult(connected=False)
    if isinstance(result, ProviderReauthRequired):
        return CalendarResult(needs_reauth=True, partial_failures=["calendar"])
    if isinstance(result, (ToolError, httpx.HTTPError, ValueError, KeyError)):
        _log.warning("Calendar fetch failed: %s", describe_error(result))
        return CalendarResult(partial_failures=["calendar"])
    if isinstance(result, BaseException):
        raise result
    # A null or non-dict body is a failed fetch, never an empty calendar.
    if not isinstance(result, dict):
        _log.warning("Calendar fetch returned %s body", type(result).__name__)
        return CalendarResult(partial_failures=["calendar"])
    items = result.get("items") or []
    if not isinstance(items, list):
        _log.warning("Calendar fetch returned non-list items: %s", type(items).__name__)
        return CalendarResult(partial_failures=["calendar"])
    truncated = bool(result.get("nextPageToken"))
    return CalendarResult(
        events=items,
        calendar_truncated=truncated,
        partial_failures=["calendar_truncated"] if truncated else [],
    )


def parse_gmail_result(result: Any) -> GmailResult:
    """Dispatch a raw gather() result to a GmailResult.

    ProviderNotLinked and ProviderReauthRequired both subclass ToolError, so
    the specific types are tested first — the generic ToolError branch would
    otherwise swallow them and incorrectly treat reauth as a transient error.
    """
    if isinstance(result, ProviderNotLinked):
        return GmailResult(connected=False)
    if isinstance(result, ProviderReauthRequired):
        return GmailResult(needs_reauth=True, partial_failures=["gmail"])
    if isinstance(result, (ToolError, httpx.HTTPError, ValueError, KeyError)):
        _log.warning("Gmail fetch failed: %s", describe_error(result))
        return GmailResult(partial_failures=["gmail"])
    if isinstance(result, BaseException):
        raise result
    body = result or {}
    return GmailResult(
        threads=body.get("threads") or [],
        threads_truncated=bool(body.get("nextPageToken")),
    )


# ── Calendly ──────────────────────────────────────────────────────────────

CALENDLY_API = "https://api.calendly.com"
CALENDLY_PAGE_SIZE = 100


@dataclass
class CalendlyFetchResult:
    """Outcome of the live Calendly read.

    Defaults represent the "not connected" state so every early-exit path is
    valid without extra logic: `connected=False` means the integration is
    absent; the route degrades to "unknown" without any further inspection.
    """

    connected: bool = False
    needs_reauth: bool = False
    events: list[Any] = field(default_factory=list)
    truncated: bool = False
    partial_failure: bool = False


def calendar_time_bounds(start_date: date, end_date: date) -> tuple[str, str]:
    """ISO strings bracketing a travel window with one day of margin each side.

    The extra margin ensures a timed event near a boundary is fetched; the
    service layer performs the precise overlap test.
    """
    time_min = datetime.combine(
        start_date - timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    # +2 days at midnight is the exclusive bound that covers all of end_date + 1.
    time_max = datetime.combine(
        end_date + timedelta(days=2), time.min, tzinfo=timezone.utc
    )
    return time_min.isoformat(), time_max.isoformat()


async def _find_calendly_integration(
    user_id: str, db: AsyncSession
) -> Integration | None:
    """The caller's own Calendly row. Personal integration: no shared fallback."""
    return await db.scalar(
        select(Integration).where(
            Integration.slug == "calendly",
            Integration.user_id == user_id,
            Integration.status.in_(ACTIVE_STATUSES),
        )
    )


async def _fetch_calendly_events(
    user_uri: str, api_key: str, time_min: str, time_max: str
) -> dict[str, Any]:
    """Single-page fetch of active Calendly events in the given window.

    Returns a dict — callers check `.get("collection")`. A non-object
    response body is returned as `{}` so the caller treats it as a partial
    failure rather than crashing on `.get`.
    """
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(
            f"{CALENDLY_API}/scheduled_events",
            headers={"Authorization": f"Bearer {api_key}"},
            params={
                "user": user_uri,
                "status": "active",
                "count": CALENDLY_PAGE_SIZE,
                "min_start_time": time_min,
                "max_start_time": time_max,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}


async def resolve_calendly(
    user_id: str, db: AsyncSession, start_date: date, end_date: date
) -> CalendlyFetchResult:
    """Live read of the caller's Calendly meetings for the trip window.

    Known failures become flags (a 401/403 is reauth, anything else from the
    provider is a partial failure) so the route stays always-200. Database and
    decryption errors propagate: a broken environment must be a loud 500, not a
    silent "unknown".
    """
    integration = await _find_calendly_integration(user_id, db)
    if integration is None:
        return CalendlyFetchResult()
    if integration.status == "expired":
        return CalendlyFetchResult(connected=True, needs_reauth=True)

    creds = await db.scalar(
        select(ApiKeyCredential).where(
            ApiKeyCredential.integration_id == integration.id
        )
    )
    if creds is None:
        return CalendlyFetchResult(connected=True, partial_failure=True)
    config = integration.config if isinstance(integration.config, dict) else {}
    extra = creds.extra if isinstance(creds.extra, dict) else {}
    user_uri = config.get("user_uri") or extra.get("user_uri")
    if not isinstance(user_uri, str) or not user_uri:
        return CalendlyFetchResult(connected=True, partial_failure=True)

    time_min, time_max = calendar_time_bounds(start_date, end_date)
    try:
        body = await _fetch_calendly_events(
            user_uri, decrypt(creds.encrypted_key), time_min, time_max
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            integration.status = "expired"
            integration.last_error = (
                f"HTTPStatusError (HTTP {exc.response.status_code})"
            )
            await db.commit()
            return CalendlyFetchResult(connected=True, needs_reauth=True)
        _log.warning(
            "Trip-feasibility Calendly read failed: HTTP %s", exc.response.status_code
        )
        return CalendlyFetchResult(connected=True, partial_failure=True)
    except (httpx.HTTPError, ValueError) as exc:
        _log.warning("Trip-feasibility Calendly read failed: %s", type(exc).__name__)
        return CalendlyFetchResult(connected=True, partial_failure=True)

    events = body.get("collection")
    if not isinstance(events, list):
        return CalendlyFetchResult(connected=True, partial_failure=True)
    pagination = body.get("pagination")
    has_more = isinstance(pagination, dict) and bool(pagination.get("next_page_token"))
    return CalendlyFetchResult(
        connected=True,
        events=events,
        truncated=has_more or len(events) >= CALENDLY_PAGE_SIZE,
    )
