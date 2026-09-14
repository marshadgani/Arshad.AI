"""Upstream-response handling: turn a third party's response into either a
dict or a clean IntegrationError — never a bare exception.

Why this module exists
----------------------
The router maps only IntegrationError to a 4xx integration-error response.
Anything else a provider raises escapes as an unhandled 500. So every place
that hands an upstream response body to a provider-supplied callback needs
the same three-branch policy:

1. callback raised IntegrationError  → deliberate rejection; pass through
   verbatim so the provider's own code/message reaches the client.
2. callback raised anything else     → an unshaped/unexpected body; wrap in
   IntegrationError so it becomes a 4xx, not a 500.
3. no callback declared              → ``{"ok": True}``.

That policy was copy-pasted into project/_factory.py (probe and sync) and
personal/_oauth_base.py, which is exactly why FEAT-146's Slack fix had to be
applied in more than one place to be complete. It lives here once now: the
packages depend on this policy module rather than on each other, and a new
provider family gets the guarantee by calling guarded_parse() instead of by
re-deriving it correctly from memory.

This module deliberately knows nothing about the database, Integration rows,
or HTTP transport. Side effects that a failure should trigger (marking an
integration row 'error', for instance) stay with the caller and are supplied
via the ``on_error`` hook, so this stays a pure policy layer.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from .base import IntegrationError

__all__ = ["decode_json", "describe", "guarded_parse", "safe_reason"]

_log = logging.getLogger(__name__)

# Error messages are surfaced to the client, so upstream-derived text is
# truncated rather than echoed unbounded.
_MAX_MESSAGE_CHARS = 300

ParseCallback = Callable[[Any], dict[str, Any]]
ErrorHook = Callable[[Exception], Awaitable[None]]

_NON_PRINTABLE = re.compile(r"[^\x20-\x7e]")


def safe_reason(value: Any, *, limit: int = 64) -> str:
    """Sanitise upstream-supplied text before echoing it in an error message.

    Third-party payloads are untrusted input: control characters (and
    anything else outside printable ASCII) are stripped so an upstream error
    string cannot inject escape sequences into a log line or a client-facing
    message, and the result is truncated.
    """
    return _NON_PRINTABLE.sub("", str(value if value else "unknown"))[:limit]


def describe(exc: Exception) -> str:
    """Default client-facing rendering of an unexpected parse failure."""
    return f"{type(exc).__name__}: {exc}"


def decode_json(resp: Any, *, provider_name: str) -> Any:
    """Decode a response body, converting a non-JSON body into an
    IntegrationError.

    A malformed body (an upstream proxy's HTML error page, say) raises
    ValueError from ``resp.json()``. ValueError is not an httpx.HTTPError, so
    a caller that only guards against transport failures would let it escape
    as a 500.
    """
    try:
        return resp.json()
    except ValueError as exc:
        raise IntegrationError(
            "probe_parse_failed",
            f"Could not read {provider_name}'s response: invalid JSON.",
        ) from exc


async def guarded_parse(
    parse: ParseCallback | None,
    body: Any,
    *,
    provider_name: str,
    stage: str,
    error_code: str,
    message: Callable[[Exception], str] = describe,
    on_error: ErrorHook | None = None,
) -> dict[str, Any]:
    """Run a provider's parse callback under the three-branch policy above.

    ``stage`` names the lifecycle step ('probe', 'sync') for the log line.
    ``message`` builds the client-facing text for an unexpected failure from
    the original exception (defaults to ``describe``); the result is
    truncated to _MAX_MESSAGE_CHARS.
    ``on_error``, when supplied, is awaited with the *original* exception
    (branch 2) or the provider's own IntegrationError (branch 1) before the
    exception continues to propagate — that distinction matters because it
    decides what gets recorded as the integration's last_error.
    """
    if parse is None:
        return {"ok": True}
    try:
        return parse(body)
    except IntegrationError as exc:
        if on_error is not None:
            await on_error(exc)
        raise
    except Exception as exc:  # noqa: BLE001
        _log.warning("%s %s parse failed", provider_name, stage, exc_info=True)
        if on_error is not None:
            await on_error(exc)
        raise IntegrationError(error_code, message(exc)[:_MAX_MESSAGE_CHARS]) from exc
