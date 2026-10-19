"""Drive HTTP client layer: list recent files from the Drive API.

Raises httpx.HTTPStatusError / httpx.RequestError on failure.
Callers are responsible for error handling and integration-state recording.

Logging discipline: only file counts and truncation flags are logged —
never file names, ids, or token values.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ._constants import _FIELDS, _FILES_URL, _PAGE_CAP

logger = logging.getLogger(__name__)


class MalformedDriveResponse(ValueError):
    """Drive answered 200 but the body is not the documented file list."""


async def list_recent_files(
    access_token: str, *, limit: int = 20, page_cap: int = _PAGE_CAP
) -> tuple[list[dict[str, Any]], bool]:
    """Return (files, truncated): newest-modified files first, up to ``limit``.

    Paginates Drive up to ``page_cap`` pages. ``truncated`` is True when more
    results existed than were returned — callers should surface this to clients.
    """
    files: list[dict[str, Any]] = []
    page_token: str | None = None
    truncated = False
    async with httpx.AsyncClient(timeout=15.0) as client:
        for _ in range(page_cap):
            params: dict[str, Any] = {
                "pageSize": min(limit, 100),
                "orderBy": "modifiedTime desc",
                "q": "trashed=false",
                "fields": _FIELDS,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = await client.get(
                _FILES_URL,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            try:
                body = resp.json()
            except ValueError as exc:
                raise MalformedDriveResponse("Drive reply is not JSON") from exc
            page = body.get("files") if isinstance(body, dict) else None
            if not isinstance(page, list):
                raise MalformedDriveResponse("Drive reply has no file list")
            files.extend(page)
            page_token = body.get("nextPageToken")
            if len(files) >= limit or not page_token:
                break
    if len(files) > limit:
        files = files[:limit]
        truncated = True
    elif page_token:
        truncated = True
    logger.info("Drive audit fetched %d files (truncated=%s)", len(files), truncated)
    return files, truncated
