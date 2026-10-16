"""Auth for the agent-usage ingest endpoint.

``POST /api/v1/ai-ecosystem/log`` is written to by a Claude Code hook, which
runs outside any browser session and cannot hold a short-lived user JWT. It
authenticates with a dedicated key (``AGENT_USAGE_INGEST_KEY``) sent in the
``X-Usage-Key`` header. The key can write usage rows and nothing else.

A request with no ``X-Usage-Key`` header falls back to the normal bearer
check, so existing JWT callers keep working.

The key must be at least 32 characters. A shorter or missing value disables
the key path entirely (503), so a misconfigured deploy fails loudly instead
of accepting a guessable key.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import get_db
from ..models.user import User
from .dependencies import get_current_user

_MIN_KEY_LENGTH = 32


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": {}}},
    )


def _configured_key() -> str | None:
    key = os.getenv("AGENT_USAGE_INGEST_KEY", "")
    return key if len(key) >= _MIN_KEY_LENGTH else None


async def require_usage_writer(
    x_usage_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Allow the ingest key, or fall back to a valid user bearer token."""
    if x_usage_key is None:
        return await get_current_user(authorization=authorization, db=db)

    expected = _configured_key()
    if expected is None:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "usage_ingest_not_configured",
            "Usage ingest key is not configured on this server.",
        )
    if not hmac.compare_digest(x_usage_key.encode(), expected.encode()):
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_usage_key",
            "Usage ingest key is invalid.",
        )
    return None
