"""Credential-safe exception formatting.

The single seam through which any exception is converted to a string that
may cross a trust boundary (HTTP response body, Postgres column, log
sink). httpx.HTTPStatusError.__str__() embeds the full request URL —
including query-string auth (OpenWeatherMap's ``?appid=...``, Stack
Overflow's ``?access_token=...``) — so interpolating ``str(exc)`` anywhere
a client or the database can see it leaks the credential. safe_detail()
and error_summary() never touch str(exc)/repr(exc)/exc.args; they derive
their output purely from the exception's *type* and, for HTTPStatusError,
the upstream status code.

Zero project imports on purpose (stdlib + httpx only) — every layer
(integrations, services, agents, api) can depend on this module without
risking an import cycle. backend/src/integrations/base.py re-exports
safe_detail/log_detail/LAST_ERROR_MAX_CHARS for provider modules that
already do ``from ..base import IntegrationError, ...``.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

import httpx

LAST_ERROR_MAX_CHARS: Final[int] = 500


def _strip_url(raw: str) -> str:
    """scheme://host/path only — no query, fragment, or embedded userinfo.

    Never echoes the input verbatim: on a malformed URL, returns a fixed
    placeholder rather than risking a partially-parsed string that still
    carries credential material.
    """
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "<unparseable-url>"
    if not parts.scheme or not parts.hostname:
        return "<unparseable-url>"
    return f"{parts.scheme}://{parts.hostname}{parts.path}"


def safe_detail(exc: BaseException) -> str:
    """Client- and DB-safe summary of `exc`.

    MUST NOT call str(exc), repr(exc), or format exc.args — that is
    precisely the channel a credential leaks through (see module
    docstring). Returns the exception's type name, or for
    httpx.HTTPStatusError, the type name plus the upstream HTTP status
    code. Truncated to LAST_ERROR_MAX_CHARS (defensive only — the output
    of this function is never long enough to need it, kept for a uniform
    contract with error_summary-style callers).
    """
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"{type(exc).__name__} (HTTP {exc.response.status_code})"
    else:
        detail = type(exc).__name__
    return detail[:LAST_ERROR_MAX_CHARS]


# Backwards-compatible alias — some call sites read more naturally as
# "give me the persisted/summarised form of this error". Identical to
# safe_detail(); kept as a separate name only for call-site readability.
error_summary = safe_detail


def log_detail(exc: BaseException) -> str:
    """Server-log-only summary of `exc`. NEVER return this from an HTTP
    response body and NEVER persist it to the database — it carries the
    redacted request URL (host + path, no query string) for operator
    diagnostics, which is more detail than a client or a DB row should
    ever see.
    """
    detail = safe_detail(exc)
    # httpx exceptions expose `.request` as a property that RAISES
    # RuntimeError (not AttributeError) when the exception was constructed
    # without one — e.g. httpx.ConnectError raised before a request was
    # attached. A plain getattr() does not guard against that.
    try:
        request = exc.request  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError):
        request = None
    url = getattr(request, "url", None)
    if url is not None:
        detail = f"{detail} url={_strip_url(str(url))}"
    return detail
