"""Google Drive permissions audit. Always HTTP 200 (see .claude/rules/api.md)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models.database import get_db
from src.models.user import User
from src.schemas.drive import DriveAuditResponse, DriveFile
from src.services.google_drive import DriveAuditService

router = APIRouter(prefix="/api/v1/drive", tags=["drive"])


@router.get(
    "/permissions-audit",
    response_model=DriveAuditResponse,
    summary="Audit sharing on recent Drive files",
)
async def permissions_audit(
    limit: int = Query(20, ge=1, le=100),
    stale_days: int = Query(180, ge=1, le=3650),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriveAuditResponse:
    """Lists recent Drive files with sharing flags. Read-only: open
    ``web_view_link`` in Drive to change sharing.

    ``stale_sharing`` is a proxy based on file-level modifiedTime only, not
    per-collaborator activity. It is true when the file has not been modified
    in ``stale_days`` days AND is shared beyond its owner. It does NOT reflect
    individual collaborator access (Drive Activity scope is not granted).

    ``anyone_with_link`` and ``stale_sharing`` are null when Drive did not
    return permissions (non-owned file): unknown, not safe.
    """
    result = await DriveAuditService.get_audit_results(
        current_user.id,
        db,
        limit=limit,
        stale_days=stale_days,
        now=datetime.now(timezone.utc),
    )
    return DriveAuditResponse(
        data=[
            DriveFile(
                id=f.id,
                name=f.name,
                web_view_link=f.web_view_link,
                modified_time=f.modified_time,
                anyone_with_link=f.anyone_with_link,
                stale_sharing=f.stale_sharing,
                permissions_visible=f.permissions_visible,
            )
            for f in result.files
        ],
        total=result.total,
        connected=result.connected,
        needs_reauth=result.needs_reauth,
        truncated=result.truncated,
        partial_failures=result.partial_failures,
    )
