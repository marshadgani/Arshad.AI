"""The OAuth `state` parameter: minting, verification, and field access.

Pure functions over a string — no Redis, no cookies, no HTTP. The only
ambient dependencies are the wall clock and `SECRET_KEY`, which makes
every rule encoded here (TTL, clock-skew rejection, HMAC correctness)
testable without any I/O at all.

Wire format: ``nonce.timestamp.hmac``

  nonce      token_urlsafe chars [A-Za-z0-9_-] — never contains a dot
  timestamp  decimal integer                   — never contains a dot
  hmac       hex digest                        — never contains a dot

so `split(".", 2)` is unambiguous.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

#: Lifetime of a login attempt. Bounds the signed state, the Redis entry,
#: and the browser cookie — all three expire together by construction.
STATE_TTL_SECONDS = 300


def _secret_key() -> str:
    key = os.getenv("SECRET_KEY", "")
    if not key:
        raise RuntimeError("SECRET_KEY env var is required for OAuth state signing")
    return key


def _sign(payload: str) -> str:
    return hmac.new(
        _secret_key().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def make_signed_state(nonce: str) -> str:
    """Return `nonce.timestamp.hmac` — a self-verifying OAuth state parameter."""
    ts = str(int(time.time()))
    return f"{nonce}.{ts}.{_sign(f'{nonce}.{ts}')}"


def verify_signed_state(signed_state: str) -> bool:
    """True only if the state is structurally valid, unexpired, and HMAC-correct."""
    try:
        nonce, ts_str, sig = signed_state.split(".", 2)
        ts = int(ts_str)
    except ValueError:
        return False
    age = int(time.time()) - ts
    # negative age = future-dated state (clock skew attack)
    if age < 0 or age > STATE_TTL_SECONDS:
        return False
    return hmac.compare_digest(sig, _sign(f"{nonce}.{ts_str}"))


def state_nonce(signed_state: str) -> str:
    """Nonce field. Only meaningful once `verify_signed_state` has passed."""
    return signed_state.split(".", 1)[0]


def state_age_seconds(signed_state: str) -> int | None:
    """Age in seconds, or None if the timestamp field is unreadable.

    Diagnostic only (it feeds the rejection log line), so an unparseable
    state degrades to None rather than raising into the request path.
    """
    try:
        return int(time.time()) - int(signed_state.split(".", 2)[1])
    except (IndexError, ValueError):
        return None
