"""Public base URLs of the deployed frontend and backend.

Before this module there were four independent copies of "read
FRONTEND_URL and strip the trailing slash" — in `auth/routers.py`,
`integrations/routers.py` (as `_frontend_url_env`), `integrations/personal/
_oauth_base.py`, and `integrations/personal/_shared.py` — plus a private
cross-module import (`attach_callback.py` reaching into `_shared._frontend_url`)
to avoid making it five. Every OAuth redirect target in the app is built
from one of these values, so a drift between copies is a drift between
where login lands and where "Connect" lands.

Two deliberately different failure modes are preserved verbatim, because
callers depend on them:

  * ``frontend_url()`` falls back to the local dev origin when
    FRONTEND_URL is unset. Used by the login and attach redirects, which
    must still work on a developer's laptop with a bare `.env`.
  * ``require_frontend_url()`` / ``require_backend_url()`` raise KeyError
    when unset. Used by the Phase-H per-slug OAuth providers
    (`integrations/personal/_oauth_base.py`), where silently substituting
    localhost would register a redirect_uri the provider rejects at
    consent time — a loud failure at call time is the safer contract.
"""

from __future__ import annotations

import os
from typing import Final

FRONTEND_URL_ENV: Final[str] = "FRONTEND_URL"
BACKEND_URL_ENV: Final[str] = "BACKEND_URL"

DEFAULT_FRONTEND_URL: Final[str] = "http://localhost:3000"


def _normalise(raw: str) -> str:
    """Drop trailing slashes so callers can concatenate `/path` safely."""
    return raw.rstrip("/")


def frontend_url() -> str:
    """Frontend origin, defaulting to the local dev server when unset."""
    return _normalise(os.getenv(FRONTEND_URL_ENV, DEFAULT_FRONTEND_URL))


def require_frontend_url() -> str:
    """Frontend origin. Raises KeyError when FRONTEND_URL is unset."""
    return _normalise(os.environ[FRONTEND_URL_ENV])


def require_backend_url() -> str:
    """Backend origin. Raises KeyError when BACKEND_URL is unset."""
    return _normalise(os.environ[BACKEND_URL_ENV])
