"""Domain catalogue + sidebar nav endpoints — Phase A."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.models import domain as m
from src.models.database import get_db
from src.schemas import domain as s

router = APIRouter(prefix="/api/v1", tags=["domains"])


@router.get("/domains", summary="List all domains (summary)")
async def list_domains(db: AsyncSession = Depends(get_db)):
    items = (await db.execute(select(m.Domain).order_by(m.Domain.slug))).scalars().all()
    return {
        "data": [
            s.DomainSummary.model_validate(d).model_dump(by_alias=True) for d in items
        ],
        "total": len(items),
    }


@router.get("/domains/{slug}", summary="Full domain config (kpis, apps, agents, feed)")
async def get_domain(slug: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(m.Domain)
        .where(m.Domain.slug == slug)
        .options(
            selectinload(m.Domain.kpis),
            selectinload(m.Domain.applications),
            selectinload(m.Domain.agents),
            selectinload(m.Domain.feed),
        )
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "domain_not_found",
                    "message": f"No domain with slug '{slug}'.",
                    "details": {"slug": slug},
                }
            },
        )
    return {
        "data": s.DomainConfigResponse.model_validate(obj).model_dump(by_alias=True)
    }


@router.get("/nav", summary="Sidebar nav items")
async def list_nav(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.NavItem).order_by(m.NavItem.ord))).scalars().all()
    )
    return {
        "data": [
            s.NavItemResponse.model_validate(n).model_dump(by_alias=True) for n in items
        ],
        "total": len(items),
    }
