"""Error-envelope construction for the auth package.

Every auth failure leaves the app as the `.claude/rules/api.md` shape:

    {"error": {"code": "...", "message": "...", "details": {}}}

Kept as one function so route handlers and the login-flow orchestration
below them cannot drift into two different error shapes. (`agents/`,
`api/v1/chat.py` and `tools/` each still carry their own private copy of
this helper — collapsing all four into a shared `src/common` module is a
worthwhile follow-up, deliberately out of scope here because it would
touch three packages unrelated to this change.)
"""

from __future__ import annotations

from fastapi import HTTPException


def envelope(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": {}}},
    )
