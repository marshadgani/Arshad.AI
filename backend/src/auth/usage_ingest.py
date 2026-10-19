"""Auth for the agent-usage ingest endpoint.

``POST /api/v1/ai-ecosystem/log`` is written to by a Claude Code hook, which
runs outside any browser session and cannot hold a short-lived user JWT. It
authenticates with a dedicated key (``AGENT_USAGE_INGEST_KEY``) sent in the
``X-Usage-Key`` header. The key can write usage rows and nothing else.

A request with no ``X-Usage-Key`` header falls back to the normal bearer
check, so existing JWT callers keep working. This is a deliberate departure
from api.md's "every route needs a bearer token" rule.

Rotation: set ``AGENT_USAGE_INGEST_KEY_NEXT`` to the new key, update the
hook's ``ARSHAD_USAGE_KEY``, then move the new value into
``AGENT_USAGE_INGEST_KEY`` and clear ``_NEXT``. Both are accepted meanwhile.

Keys must be at least 32 characters. A shorter or missing value is ignored.
A wrong key and an unconfigured server both answer with the same 401 so a
caller cannot probe whether a key is set. The real reason goes to the server
log, never the key itself.
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.errors import http_error
from ..models.database import get_db
from ..models.user import User
from .dependencies import get_current_user

_log = logging.getLogger(__name__)

_MIN_KEY_LENGTH = 32
_KEY_ENV_VARS = ("AGENT_USAGE_INGEST_KEY", "AGENT_USAGE_INGEST_KEY_NEXT")


def _configured_keys() -> list[str]:
    keys = (os.getenv(name, "") for name in _KEY_ENV_VARS)
    return [key for key in keys if len(key) >= _MIN_KEY_LENGTH]


def _invalid_key() -> Exception:
    return http_error(
        status.HTTP_401_UNAUTHORIZED,
        "invalid_usage_key",
        "Usage ingest key is invalid.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_usage_writer(
    x_usage_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Allow the ingest key, or fall back to a valid user bearer token."""
    if x_usage_key is None:
        return await get_current_user(authorization=authorization, db=db)

    expected = _configured_keys()
    if not expected:
        _log.warning(
            "Usage ingest rejected: no AGENT_USAGE_INGEST_KEY of 32+ characters "
            "is configured on this server."
        )
        raise _invalid_key()

    presented = x_usage_key.encode()
    # Compare against every key without short-circuiting.
    matches = [hmac.compare_digest(presented, key.encode()) for key in expected]
    if not any(matches):
        _log.warning("Usage ingest rejected: X-Usage-Key does not match.")
        raise _invalid_key()
    return None
