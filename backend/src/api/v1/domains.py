"""Domain catalogue + sidebar nav endpoints — Phase A."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.auth.dependencies import get_current_user
from src.models import domain as m
from src.models.database import get_db
from src.models.integration import Integration
from src.models.user import User
from src.schemas import domain as s
from src.services import domain_live

router = APIRouter(
    prefix="/api/v1",
    tags=["domains"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/domains", summary="List all domains (summary)")
async def list_domains(db: AsyncSession = Depends(get_db)):
    items = (await db.execute(select(m.Domain).order_by(m.Domain.slug))).scalars().all()
    return {
        "data": [
            s.DomainSummary.model_validate(d).model_dump(by_alias=True) for d in items
        ],
        "total": len(items),
    }


# Domains whose pages are honestly "coming soon": no integration backs them yet,
# so the API serves no applications, KPIs, agents or feed for them.
_COMING_SOON = {"travel", "home", "learning"}

_LIVE_KPI_SOURCES = {
    "finance": ("plaid",),
    "stocks": ("zerodha_kite", "upstox"),
}


async def _live_kpis(slug: str, user: User, db: AsyncSession) -> list[dict]:
    sources = _LIVE_KPI_SOURCES.get(slug)
    if not sources:
        return []
    rows = (
        (
            await db.execute(
                select(Integration).where(
                    Integration.user_id == user.id,
                    Integration.slug.in_(sources),
                    Integration.status == "connected",
                )
            )
        )
        .scalars()
        .all()
    )
    configs = [r.config for r in rows]
    if slug == "finance":
        return domain_live.build_finance_kpis(configs[0] if configs else None)
    return domain_live.build_stocks_kpis(configs)


@router.get("/domains/{slug}", summary="Full domain config (kpis, apps, agents, feed)")
async def get_domain(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    data = s.DomainConfigResponse.model_validate(obj).model_dump(by_alias=True)
    # The seeded agents/feed rows are fabricated telemetry and the seeded KPIs
    # are static numbers; serve real values or nothing.
    data["kpis"] = await _live_kpis(slug, current_user, db)
    data["agents"] = []
    data["feed"] = []
    if slug in _COMING_SOON:
        data["status"] = "coming_soon"
        data["applications"] = []
    return {"data": data}


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
