"""REST endpoints for the integrations layer.

GET    /api/v1/integrations
       List all known providers + per-(user,slug) status. Returns both
       personal_oauth (filtered by current user) and project_apikey rows.

POST   /api/v1/integrations/{slug}/connect
       OAuth → returns {redirect_url}. API-key → body {api_key}.

POST   /api/v1/integrations/{slug}/sync
       Triggers a sync. Returns {rows_written, summary, duration_ms}.

POST   /api/v1/integrations/{slug}/disconnect
       Marks integration disconnected; revokes upstream where possible.

GET    /api/v1/integrations/{slug}/status
       Returns the latest status snapshot.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..models.database import get_db
from ..models.integration import Integration
from ..models.user import User
from .base import IntegrationError, IntegrationProvider
from .registry import INTEGRATION_REGISTRY, get_provider

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


def _provider_descriptor(p: IntegrationProvider) -> dict[str, Any]:
    return {
        "slug": p.slug,
        "kind": p.kind,
        "display_name": p.display_name,
        "category": p.category,
        "description": p.description,
        "docs_url": p.docs_url,
        "icon": p.icon,
        "coming_soon": p.coming_soon,
        "coming_soon_reason": p.coming_soon_reason,
    }


def _envelope(code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"error": {"code": error_code, "message": message, "details": {}}},
    )


@router.get("", summary="List integrations + per-user status")
async def list_integrations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(Integration).where(
                (Integration.user_id == user.id) | (Integration.user_id.is_(None))
            )
        )
    ).all()
    by_slug: dict[str, Integration] = {r.slug: r for r in rows}

    items = []
    for provider in INTEGRATION_REGISTRY.values():
        meta = _provider_descriptor(provider)
        existing = by_slug.get(provider.slug)
        if existing is not None:
            try:
                report = await provider.status(integration=existing, db=db)
                meta["status"] = report.status
                meta["last_synced_at"] = report.last_synced_at
                meta["last_error"] = report.last_error
                meta["extra"] = report.extra
            except Exception as exc:  # noqa: BLE001
                meta["status"] = "error"
                meta["last_error"] = f"{type(exc).__name__}: {exc}"
                meta["extra"] = {}
        else:
            meta["status"] = "disconnected"
            meta["last_synced_at"] = None
            meta["last_error"] = None
            meta["extra"] = {}
        items.append(meta)

    items.sort(key=lambda m: (m["category"], m["display_name"]))
    return {"data": items, "total": len(items)}


@router.post("/{slug}/connect", summary="Start a connection")
async def connect_integration(
    slug: str,
    payload: dict[str, Any] | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = get_provider(slug)
    if provider is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "unknown_integration",
            f"No integration '{slug}'.",
        )
    try:
        result = await provider.connect(user=user, db=db, payload=payload or {})
    except IntegrationError as exc:
        raise _envelope(status.HTTP_400_BAD_REQUEST, exc.code, exc.message)
    return {
        "data": {
            "integration_id": result.integration_id,
            "redirect_url": result.redirect_url,
        }
    }


@router.post("/{slug}/sync", summary="Trigger sync")
async def sync_integration(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = get_provider(slug)
    if provider is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "unknown_integration",
            f"No integration '{slug}'.",
        )
    integration = await db.scalar(
        select(Integration).where(
            Integration.slug == slug,
            (Integration.user_id == user.id) | (Integration.user_id.is_(None)),
        )
    )
    if integration is None:
        raise _envelope(
            status.HTTP_400_BAD_REQUEST,
            "not_connected",
            f"Integration '{slug}' is not connected. Connect it first.",
        )
    try:
        result = await provider.sync(integration=integration, db=db)
    except IntegrationError as exc:
        raise _envelope(status.HTTP_400_BAD_REQUEST, exc.code, exc.message)
    return {
        "data": {
            "rows_written": result.rows_written,
            "summary": result.summary,
            "duration_ms": result.duration_ms,
        }
    }


@router.post("/{slug}/disconnect", summary="Disconnect integration")
async def disconnect_integration(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = get_provider(slug)
    if provider is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "unknown_integration",
            f"No integration '{slug}'.",
        )
    integration = await db.scalar(
        select(Integration).where(
            Integration.slug == slug,
            (Integration.user_id == user.id) | (Integration.user_id.is_(None)),
        )
    )
    if integration is None:
        return {"data": {"status": "already_disconnected"}}
    await provider.disconnect(integration=integration, db=db)
    return {"data": {"status": "disconnected"}}


@router.get("/{slug}/status", summary="Get latest status")
async def integration_status(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = get_provider(slug)
    if provider is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "unknown_integration",
            f"No integration '{slug}'.",
        )
    integration = await db.scalar(
        select(Integration).where(
            Integration.slug == slug,
            (Integration.user_id == user.id) | (Integration.user_id.is_(None)),
        )
    )
    if integration is None:
        return {
            "data": {
                "slug": slug,
                "status": "disconnected",
                "last_synced_at": None,
                "last_error": None,
                "extra": {},
            }
        }
    report = await provider.status(integration=integration, db=db)
    return {
        "data": {
            "slug": slug,
            "status": report.status,
            "last_synced_at": report.last_synced_at,
            "last_error": report.last_error,
            "extra": report.extra,
        }
    }
