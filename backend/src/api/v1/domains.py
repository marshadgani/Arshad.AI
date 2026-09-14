"""Domain catalogue + sidebar nav endpoints — Phase A."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.auth.dependencies import get_current_user
from src.models import domain as m
from src.models.database import get_db
from src.schemas import domain as s

router = APIRouter(
    prefix="/api/v1",
    tags=["domains"],
    dependencies=[Depends(get_current_user)],
)

# domain_feed_rows grows without bound over the app's lifetime; the panel
# only ever displays "last 24 h" activity, so cap what's fetched rather
# than pulling the domain's entire history on every page load.
FEED_ROW_LIMIT = 20


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

    # Fetched separately (bounded + ordered) instead of via selectinload,
    # which would pull every feed row the domain has ever accumulated —
    # see FEED_ROW_LIMIT comment above. Deliberately NOT assigned onto
    # obj.feed: that relationship cascades "all, delete-orphan", so
    # replacing its collection would first lazy-load the domain's full
    # (unbounded) existing feed to diff against, then mark every row
    # outside this bounded page as an orphan to be deleted on the next
    # flush — silently destroying older feed history. Building the
    # response schema field-by-field avoids ever touching that attribute.
    feed_stmt = (
        select(m.DomainFeedRow)
        .where(m.DomainFeedRow.domain_slug == slug)
        .order_by(m.DomainFeedRow.created_at.desc())
        .limit(FEED_ROW_LIMIT)
    )
    feed_rows = (await db.execute(feed_stmt)).scalars().all()

    config = s.DomainConfigResponse(
        slug=obj.slug,
        title=obj.title,
        emoji=obj.emoji,
        tagline=obj.tagline,
        kpis=[s.DomainKPIResponse.model_validate(k) for k in obj.kpis],
        applications=[
            s.DomainApplicationResponse.model_validate(a) for a in obj.applications
        ],
        agents=[s.DomainAgentResponse.model_validate(a) for a in obj.agents],
        feed=[s.DomainFeedRowResponse.model_validate(f) for f in feed_rows],
    )
    return {"data": config.model_dump(by_alias=True)}


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
