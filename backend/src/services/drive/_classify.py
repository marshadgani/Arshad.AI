"""Pure classification logic: parse Drive timestamps and flag sharing issues.

All functions here are side-effect-free. Clocks are injected as parameters
so callers control time in tests and production alike.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ._models import FileAuditResult


def _parse_time(value: Any) -> datetime | None:
    """Parse an ISO-format datetime string into a timezone-aware datetime.

    Returns None for empty, non-string, or unparseable values rather than
    raising — Drive timestamps are user-visible metadata and vary in format.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def classify_files(
    files: list[dict[str, Any]], *, now: datetime, stale_days: int
) -> list[FileAuditResult]:
    """Flag public links and stale sharing on a list of raw Drive file dicts.

    ``stale_sharing`` is a proxy: the file was last modified more than
    ``stale_days`` ago AND is shared beyond its owner. It is not
    per-collaborator activity (Drive Activity scope is not granted).
    ``None`` flags mean Drive returned no permissions for the file (not
    owned by the user): unknown, never "safe".

    Pure: the clock is injected via ``now`` so tests remain deterministic.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=stale_days)
    results: list[FileAuditResult] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        file_id = f.get("id")
        if not file_id:
            continue
        permissions = [p for p in (f.get("permissions") or []) if isinstance(p, dict)]
        visible = bool(permissions)
        modified = _parse_time(f.get("modifiedTime"))
        anyone: bool | None = None
        stale: bool | None = None
        if visible:
            anyone = any(p.get("type") == "anyone" for p in permissions)
            shared = any(p.get("role") != "owner" for p in permissions)
            stale = None if modified is None else (shared and modified < cutoff)
        results.append(
            FileAuditResult(
                id=file_id,
                name=f.get("name") or "",
                web_view_link=f.get("webViewLink") or "",
                modified_time=f.get("modifiedTime") or "",
                anyone_with_link=anyone,
                stale_sharing=stale,
                permissions_visible=visible,
            )
        )
    return results
