"""External provider (Google Calendar, Gmail) fetch and result-parsing for the
Shopify intelligence layer.

Centralises the ProviderNotLinked / ProviderReauthRequired / ToolError /
BaseException isinstance dispatch so neither the route handler nor any
domain-service module needs to perform that dance. Both routes that use
these providers (get_inventory_cover, get_service_debt) previously duplicated
the same isinstance chain; now they call parse_calendar_result /
parse_gmail_result and receive a typed dataclass.

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
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.base import ProviderNotLinked, ProviderReauthRequired, ToolError

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
        },
    )


async def list_gmail_threads(db: AsyncSession, user: User) -> dict | None:
    """Raw Gmail threads response — suitable as a gather() coroutine.

    Callers pass the result to parse_gmail_result; they never inspect it
    directly.
    """
    from src.tools.clients import gmail  # deferred: see module docstring

    return await gmail.request(
        db=db,
        user=user,
        method="GET",
        path="users/me/threads",
        params={"q": GMAIL_UNANSWERED_QUERY, "maxResults": GMAIL_PAGE_SIZE},
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
    if isinstance(result, (ToolError, httpx.HTTPError)):
        _log.warning("Calendar fetch failed: %s", result)
        return CalendarResult(partial_failures=["calendar"])
    if isinstance(result, BaseException):
        raise result
    body = result or {}
    failures: list[str] = []
    if body.get("nextPageToken"):
        failures.append("calendar_truncated")
    return CalendarResult(events=body.get("items") or [], partial_failures=failures)


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
    if isinstance(result, (ToolError, httpx.HTTPError)):
        _log.warning("Gmail fetch failed: %s", result)
        return GmailResult(partial_failures=["gmail"])
    if isinstance(result, BaseException):
        raise result
    body = result or {}
    return GmailResult(
        threads=body.get("threads") or [],
        threads_truncated=bool(body.get("nextPageToken")),
    )
