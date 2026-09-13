"""OAuth login-state primitives, split by concern.

    signing.py  the `state` parameter (pure crypto + clock, no I/O)
    store.py    the single-use Redis record (fail-closed, no HTTP)
    cookies.py  cookie names, attributes, and value validity

`auth/routers.py` composes these into the login/callback flow; it is the
only module that knows how the three fit together, and the only one that
maps a failure onto an HTTP status.
"""

from .cookies import (
    BINDER_BYTES,
    BINDER_COOKIE_NAME,
    BINDER_LEN,
    NONCE_COOKIE_NAME,
    clear_login_cookie,
    cookie_is_secure,
    is_valid_binder,
    mint_binder,
    set_login_cookie,
)
from .signing import (
    STATE_TTL_SECONDS,
    make_signed_state,
    state_age_seconds,
    state_nonce,
    verify_signed_state,
)
from .store import (
    REDIS_ERRORS,
    LoginStateUnavailable,
    login_nonce_key,
    put_state,
    take_state,
)

__all__ = [
    "BINDER_BYTES",
    "BINDER_COOKIE_NAME",
    "BINDER_LEN",
    "NONCE_COOKIE_NAME",
    "REDIS_ERRORS",
    "STATE_TTL_SECONDS",
    "LoginStateUnavailable",
    "clear_login_cookie",
    "cookie_is_secure",
    "is_valid_binder",
    "login_nonce_key",
    "make_signed_state",
    "mint_binder",
    "put_state",
    "set_login_cookie",
    "state_age_seconds",
    "state_nonce",
    "take_state",
    "verify_signed_state",
]
