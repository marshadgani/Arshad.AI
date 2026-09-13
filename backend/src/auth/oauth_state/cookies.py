"""Cookie policy for the login round trip.

One module owns cookie *names*, *attributes*, and *value validity*, so
the set-side and the clear-side can never disagree on attributes (a
mismatch there silently leaves a stale cookie in the jar) and no route
handler has to remember `httponly=True, samesite="lax"` by hand.

Both cookies are scoped to the backend's own origin. That only holds if
the login leg is an absolute top-level navigation to the backend — see
the module docstring of `backend/src/auth/routers.py` for why (FEAT-142).
"""

from __future__ import annotations

import os
import secrets

from fastapi import Response

#: Flag-off (shipping) model: the cookie value IS the per-attempt nonce.
NONCE_COOKIE_NAME = "oauth_login_nonce"

#: Flag-on (W2, designed not wired) model: one long-lived per-browser
#: binder shared across concurrent attempts; Redis holds sha256(binder).
BINDER_COOKIE_NAME = "oauth_browser_binder"

BINDER_BYTES = 32
#: Derived, never hard-coded — changing BINDER_BYTES must not silently
#: make every real cookie "malformed" (regression pinned by test T14).
BINDER_LEN = len(secrets.token_urlsafe(BINDER_BYTES))

_BINDER_CHARSET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)


def cookie_is_secure() -> bool:
    # https backend (Render prod) -> Secure cookie required by browsers.
    # http backend (local dev)    -> Secure would silently drop the cookie.
    return os.getenv("BACKEND_URL", "").startswith("https")


def is_valid_binder(value: str) -> bool:
    return len(value) == BINDER_LEN and all(c in _BINDER_CHARSET for c in value)


def mint_binder(existing: str | None) -> str:
    """Reuse the browser's current binder when it is well-formed, else mint one.

    Reuse is what makes two overlapping login attempts from the same
    browser both verifiable: the second `/login` must not overwrite the
    cookie the first attempt's callback is still going to present.
    """
    if existing and is_valid_binder(existing):
        return existing
    return secrets.token_urlsafe(BINDER_BYTES)


def set_login_cookie(
    response: Response, name: str, value: str, *, max_age: int
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=cookie_is_secure(),
        samesite="lax",
        path="/",
    )


def clear_login_cookie(response: Response, name: str) -> None:
    response.delete_cookie(
        name,
        path="/",
        secure=cookie_is_secure(),
        samesite="lax",
    )
