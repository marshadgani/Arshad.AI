"""Single definition of the API error envelope mandated by .claude/rules/api.md.

    {"error": {"code": "snake_case", "message": "Human readable", "details": {}}}

The shape was previously re-declared as a private `_envelope()` in every
router that needed it, so a change to the contract meant editing N files and
hoping none were missed. Routers now import from here instead.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def error_body(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the bare envelope dict.

    Useful where the payload is needed without an exception — e.g. a module
    level constant for a frequently raised error, or a JSONResponse body.
    """
    return {"error": {"code": code, "message": message, "details": details or {}}}


def http_error(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """Return (do not raise) an HTTPException carrying the standard envelope.

    Returned rather than raised so call sites read `raise http_error(...)`,
    which keeps the raise visible to both readers and static analysis.
    """
    return HTTPException(
        status_code=status_code,
        detail=error_body(code, message, details),
        headers=headers,
    )
