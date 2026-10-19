"""DriveAuditService: orchestrates token fetch, HTTP calls, and classification.

This module is the only place that combines the three concerns above.
It does not contain HTTP logic, pure classification logic, or error-string
helpers — those live in their own modules and are imported here.

Logging discipline: only exception type names, HTTP status codes, and
counts are ever logged — never file names, ids, tokens, or user data.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.google_token import TokenUnavailableError
from src.services.integrations.state import find_integration, mark_healthy

from ._classify import classify_files
from ._constants import _MAX_NAME_CHARS, _MAX_SUGGESTIONS, _SLUG
from ._errors import (
    _commit_or_rollback,
    _get_token,
    _is_reauth_status,
    _record_error,
    _safe_error_str,
)
from ._http import list_recent_files
from ._models import DriveAuditResult, KnowledgeSuggestionsResult

logger = logging.getLogger(__name__)


class DriveAuditService:
    @staticmethod
    async def get_audit_results(
        user_id: uuid.UUID,
        db: AsyncSession,
        *,
        limit: int,
        stale_days: int,
        now: datetime,
    ) -> DriveAuditResult:
        integration = await find_integration(user_id, _SLUG, db)
        if integration is None:
            return DriveAuditResult()

        try:
            token = await _get_token(user_id, db)
        except TokenUnavailableError:
            return DriveAuditResult(
                connected=True,
                needs_reauth=True,
                partial_failures=["google_drive: needs_reauth"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drive token fetch failed: %s", _safe_error_str(exc))
            await _record_error(integration, exc, False, db)
            return DriveAuditResult(
                connected=True, partial_failures=["google_drive: fetch_failed"]
            )

        # Release the read transaction (and its pooled connection) before the
        # network calls. expire_on_commit=False keeps `integration` usable.
        await _commit_or_rollback(db, "Drive read transaction release failed")

        try:
            files, truncated = await list_recent_files(token, limit=limit)
        except httpx.HTTPStatusError as exc:
            reauth = _is_reauth_status(exc)
            logger.warning("Drive list failed: %s", _safe_error_str(exc))
            await _record_error(integration, exc, reauth, db)
            if reauth:
                return DriveAuditResult(
                    connected=True,
                    needs_reauth=True,
                    partial_failures=["google_drive: needs_reauth"],
                )
            status = exc.response.status_code
            label = {429: "rate_limited", 403: "forbidden"}.get(status, "fetch_failed")
            return DriveAuditResult(
                connected=True, partial_failures=[f"google_drive: {label}"]
            )
        except httpx.RequestError as exc:
            logger.warning("Drive list failed: %s", type(exc).__name__)
            await _record_error(integration, exc, False, db)
            return DriveAuditResult(
                connected=True, partial_failures=["google_drive: network_error"]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drive list failed: %s", type(exc).__name__)
            await _record_error(integration, exc, False, db)
            return DriveAuditResult(
                connected=True, partial_failures=["google_drive: unexpected_error"]
            )

        try:
            await mark_healthy(integration, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drive status reset failed: %s", type(exc).__name__)

        audited = classify_files(files, now=now, stale_days=stale_days)
        partial: list[str] = []
        if len(audited) < len(files):
            logger.warning(
                "Drive audit dropped %d unreadable entries", len(files) - len(audited)
            )
            partial.append("google_drive: unreadable_entries")
        return DriveAuditResult(
            files=audited,
            total=len(audited),
            connected=True,
            truncated=truncated,
            partial_failures=partial,
        )

    @staticmethod
    async def get_knowledge_suggestions(
        user_id: uuid.UUID, db: AsyncSession
    ) -> KnowledgeSuggestionsResult:
        """Recent Drive file names from the sync cache. Never calls Drive."""
        integration = await find_integration(user_id, _SLUG, db)
        if integration is None:
            return KnowledgeSuggestionsResult()
        if integration.status == "expired":
            return KnowledgeSuggestionsResult(
                connected=True,
                needs_reauth=True,
                partial_failures=["google_drive: needs_reauth"],
            )
        partial: list[str] = []
        if integration.status == "error":
            partial.append("google_drive: sync_error")
        config = integration.config
        if not isinstance(config, dict):
            if config:
                logger.warning("Drive cache config has unexpected shape")
                partial.append("google_drive: cache_unreadable")
            config = {}
        cached = config.get("files") or []
        if not isinstance(cached, list):
            logger.warning("Drive cache files has unexpected shape")
            partial.append("google_drive: cache_unreadable")
            cached = []
        # Deduplicate while preserving the cache's recency order.
        seen: dict[str, None] = {}
        for f in cached:
            if not isinstance(f, dict):
                continue
            name = f.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            seen[name[:_MAX_NAME_CHARS]] = None
        unique = list(seen)
        ordered = unique[:_MAX_SUGGESTIONS]
        file_count = config.get("file_count")
        truncated = (
            bool(config.get("truncated"))
            or len(unique) > _MAX_SUGGESTIONS
            or (isinstance(file_count, int) and file_count > len(cached))
        )
        return KnowledgeSuggestionsResult(
            names=ordered,
            total=len(ordered),
            connected=True,
            truncated=truncated,
            partial_failures=partial,
        )
