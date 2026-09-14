"""State primitives for the "attach a provider to the current user" OAuth flow.

This is a THIRD OAuth flow, distinct from:
  - login (auth/routers.py `_start_login`/`_handle_callback`, Redis namespace
    `login_oauth_state:`) — anonymous, always issues a JWT.
  - Phase H per-slug integrations (integrations/personal/_oauth_base.py
    `store_oauth_state`/`consume_oauth_state`, Redis namespace
    `int_oauth_state:`) — writes to `integration_oauth_tokens`, a table the
    chat tools never read.

The attach flow starts inside an authenticated POST (`/integrations/{slug}
/connect`) and must complete anonymously on the browser's top-level
redirect back from Google/GitHub — the JWT cannot ride along on that hop.
Identity is instead bound into the token at MINT time (this module is only
ever called from code that already has a verified `user.id`), then
recovered exactly once at consume time. The `att.` prefix on the token
lets auth/routers.py's login callbacks recognise an attach callback before
running any login-specific logic (cookie-nonce check, JWT issuance) —
see auth/routers.py's module docstring for the full CSRF rationale.

Deliberately NOT reusing integrations/personal/_oauth_base.py's
store_oauth_state/consume_oauth_state: that pair is a hot path shared by
ten shipped Phase-H providers, its value shape is a bare "user_id::slug"
pair (or a legacy-compatible envelope), and mixing its namespace with this
one would let a Phase-H state token be replayed into the attach callback,
or vice versa.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Final

from ..middleware.cache import get_redis

ATTACH_STATE_PREFIX: Final[str] = "att."
ATTACH_STATE_TTL_SECONDS: Final[int] = 600


class AttachError(Exception):
    """Raised by the attach flow. Routers/orchestrator map this to a
    redirect query param (`?error=<code>`) — never an HTML error page."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AttachStatePayload:
    user_id: str
    provider: str
    return_slug: str


def _key(token: str) -> str:
    return f"attach_oauth_state:{token}"


async def store_attach_state(*, user_id: str, provider: str, return_slug: str) -> str:
    """Mint a single-use attach token bound to `user_id`.

    Called only from a code path that already authenticated the caller
    (POST /integrations/{slug}/connect, behind get_current_user) — the
    user_id here is trusted, not attacker-supplied.
    """
    token = f"{ATTACH_STATE_PREFIX}{secrets.token_urlsafe(32)}"
    value = json.dumps(
        {"v": 1, "user_id": user_id, "provider": provider, "return_slug": return_slug}
    )
    redis = await get_redis()
    await redis.set(_key(token), value, ex=ATTACH_STATE_TTL_SECONDS)
    return token


async def consume_attach_state(token: str) -> AttachStatePayload | None:
    """Atomically read+delete the attach state. Returns None if the token
    is unknown, expired, already consumed, or malformed — callers redirect
    to ?error=invalid_state in every one of those cases; the distinction
    does not matter to the user."""
    redis = await get_redis()
    raw = await redis.getdel(_key(token))
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        envelope = json.loads(raw)
        return AttachStatePayload(
            user_id=str(envelope["user_id"]),
            provider=str(envelope["provider"]),
            return_slug=str(envelope["return_slug"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
