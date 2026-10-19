"""Error helpers: sanitised error strings, reauth detection, token fetch, status recording.

Logging discipline: only exception type names and HTTP status codes are
ever logged — never response bodies, file names, tokens, or user data.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.google_token import TokenUnavailableError, get_valid_google_token

from ._constants import _API_REAUTH_STATUSES, _REFRESH_REAUTH_STATUSES

logger = logging.getLogger(__name__)


def _safe_error_str(exc: Exception) -> str:
    """Return a log-safe representation: type name plus HTTP status if available."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}: status={exc.response.status_code}"
    return type(exc).__name__


def _is_reauth_status(
    exc: Exception, statuses: Sequence[int] = _API_REAUTH_STATUSES
) -> bool:
    """Drive API calls: only 401 means the grant is dead.

    A 403 is usually a rate limit and a 400 a bad request, so neither
    may mark the integration expired. Token refresh passes the wider
    400–403 range (invalid_grant).
    """
    return (
        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in statuses
    )


async def _get_token(user_id: uuid.UUID, db: AsyncSession) -> str:
    """Fetch a valid Google token; convert a 400–403 refresh error to TokenUnavailableError."""
    try:
        return await get_valid_google_token(user_id, db)
    except httpx.HTTPStatusError as exc:
        if _is_reauth_status(exc, _REFRESH_REAUTH_STATUSES):
            raise TokenUnavailableError("Token refresh rejected.") from exc
        raise


async def _commit_or_rollback(db: AsyncSession, context: str) -> None:
    """Commit the session; on failure log, attempt rollback, and log again if that fails."""
    try:
        await db.commit()
    except Exception as commit_exc:  # noqa: BLE001
        logger.warning("%s: %s", context, type(commit_exc).__name__)
        try:
            await db.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            logger.warning("Drive rollback failed: %s", type(rollback_exc).__name__)


async def _record_error(
    integration: Any, exc: Exception, reauth: bool, db: AsyncSession
) -> None:
    """Persist a sanitised error status without leaking upstream response text."""
    integration.status = "expired" if reauth else "error"
    integration.last_error = _safe_error_str(exc)
    await _commit_or_rollback(db, "Drive integration status not persisted")
