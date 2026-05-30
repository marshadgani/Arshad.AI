"""Dashboard API endpoints — Phase A + live Google Calendar / Gmail / Claude data.

/events and /briefing serve live data when Google is connected, falling back to
seeded mock rows on TokenUnavailableError. All other endpoints remain mock-only.

Every collection returns ``{"data": [...], "total": N}``; every singleton returns
``{"data": {...}}`` per ``.claude/rules/api.md``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models import dashboard as m
from src.models.database import get_db
from src.models.user import User
from src.schemas import dashboard as s
from src.services.briefing import compose_briefing
from src.services.gmail_client import fetch_unread_count
from src.services.google_calendar import fetch_todays_events
from src.services.google_token import TokenUnavailableError, get_valid_google_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _collection(items: list[Any], schema) -> dict[str, Any]:
    return {
        "data": [schema.model_validate(i).model_dump(by_alias=True) for i in items],
        "total": len(items),
    }


def _singleton(obj: Any | None, schema, name: str) -> dict[str, Any]:
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": f"{name}_not_seeded",
                    "message": f"The {name} singleton has not been seeded yet.",
                    "details": {},
                }
            },
        )
    return {"data": schema.model_validate(obj).model_dump(by_alias=True)}


# ── Singletons ─────────────────────────────────────────────────────


@router.get("/briefing", summary="Daily briefing")
async def get_briefing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        token = await get_valid_google_token(current_user.id, db)
    except TokenUnavailableError:
        obj = (await db.execute(select(m.DailyBriefing).limit(1))).scalar_one_or_none()
        return _singleton(obj, s.DailyBriefingResponse, "briefing")

    events_res, unread_res = await asyncio.gather(
        fetch_todays_events(token),
        fetch_unread_count(token),
        return_exceptions=True,
    )

    if isinstance(events_res, Exception):
        logger.warning("Calendar fetch failed in briefing (%s)", events_res)
        events = []
    else:
        events = events_res

    if isinstance(unread_res, Exception):
        logger.warning("Gmail fetch failed in briefing (%s)", unread_res)
        unread = None
    else:
        unread = unread_res

    data = await compose_briefing(events, unread)
    return {"data": data}


@router.get("/focus", summary="Current focus block")
async def get_focus(db: AsyncSession = Depends(get_db)):
    obj = (await db.execute(select(m.FocusBlock).limit(1))).scalar_one_or_none()
    return _singleton(obj, s.FocusBlockResponse, "focus")


@router.get("/weather", summary="Current weather")
async def get_weather(db: AsyncSession = Depends(get_db)):
    obj = (await db.execute(select(m.Weather).limit(1))).scalar_one_or_none()
    return _singleton(obj, s.WeatherResponse, "weather")


@router.get("/commute", summary="Current commute")
async def get_commute(db: AsyncSession = Depends(get_db)):
    obj = (await db.execute(select(m.Commute).limit(1))).scalar_one_or_none()
    return _singleton(obj, s.CommuteResponse, "commute")


# ── Collections ────────────────────────────────────────────────────


@router.get("/tasks", summary="Auto-prioritised tasks across sources")
async def list_tasks(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.Task).order_by(m.Task.priority, m.Task.id)))
        .scalars()
        .all()
    )
    return _collection(items, s.TaskResponse)


@router.get("/events", summary="Events across calendars")
async def list_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        token = await get_valid_google_token(current_user.id, db)
    except TokenUnavailableError:
        items = (await db.execute(select(m.Event).order_by(m.Event.id))).scalars().all()
        return _collection(items, s.EventResponse)

    try:
        events = await fetch_todays_events(token)
    except Exception as exc:
        logger.warning("Live calendar fetch failed (%s); falling back to mock", exc)
        items = (await db.execute(select(m.Event).order_by(m.Event.id))).scalars().all()
        return _collection(items, s.EventResponse)

    return {
        "data": [
            s.EventResponse.model_validate(asdict(e)).model_dump(by_alias=True)
            for e in events
        ],
        "total": len(events),
    }


@router.get("/agents", summary="Cross-domain agent roster")
async def list_agents(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.AgentGlobal).order_by(m.AgentGlobal.id)))
        .scalars()
        .all()
    )
    return _collection(items, s.AgentResponse)


@router.get("/decisions", summary="Decisions waiting on the user")
async def list_decisions(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.Decision).order_by(m.Decision.id))).scalars().all()
    )
    return _collection(items, s.DecisionResponse)


@router.get("/agent-activity", summary="Live agent ticker")
async def list_agent_activity(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.AgentTick).order_by(m.AgentTick.id))).scalars().all()
    )
    return _collection(items, s.AgentTickResponse)


@router.get("/notifications", summary="Notifications")
async def list_notifications(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.Notification).order_by(m.Notification.id)))
        .scalars()
        .all()
    )
    return _collection(items, s.NotificationResponse)


@router.get("/news", summary="News headlines")
async def list_news(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.NewsItem).order_by(m.NewsItem.id))).scalars().all()
    )
    return _collection(items, s.NewsResponse)


@router.get("/quick-actions", summary="Quick action shortcuts")
async def list_quick_actions(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.QuickAction).order_by(m.QuickAction.id)))
        .scalars()
        .all()
    )
    return _collection(items, s.QuickActionResponse)


@router.get("/health-habits", summary="Health and habit metrics")
async def list_health_habits(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.HealthHabit).order_by(m.HealthHabit.name)))
        .scalars()
        .all()
    )
    return _collection(items, s.HealthHabitResponse)


@router.get("/knowledge-suggestions", summary="Knowledge-search suggestions")
async def list_knowledge_suggestions(db: AsyncSession = Depends(get_db)):
    items = (
        (
            await db.execute(
                select(m.KnowledgeSuggestion).order_by(m.KnowledgeSuggestion.text)
            )
        )
        .scalars()
        .all()
    )
    return {"data": [i.text for i in items], "total": len(items)}
