"""Dashboard API endpoints — Phase A + live Google Calendar / Gmail / Claude data.

/events and /briefing serve live data when Google is connected and an honest
empty/"connect Google" response otherwise. /focus, /tasks, /decisions,
/notifications and /agent-activity are derived from the user's ingested
GitHub/Gmail rows, integration status and agent-run log. The remaining
endpoints are still seed-backed.

Every collection returns ``{"data": [...], "total": N}``; every singleton returns
``{"data": {...}}`` per ``.claude/rules/api.md``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models import dashboard as m
from src.models.ai_ecosystem import AgentUsageLog
from src.models.conversation import ConversationSession
from src.models.database import get_db
from src.models.ingested import IngestedGitHubActivity
from src.models.integration import Integration
from src.models.user import User
from src.schemas import dashboard as s
from src.services import ambient
from src.services import dashboard_live as live
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


async def _github_rows(db: AsyncSession, user_id) -> list[IngestedGitHubActivity]:
    stmt = (
        select(IngestedGitHubActivity)
        .where(
            IngestedGitHubActivity.user_id == user_id,
            IngestedGitHubActivity.raw["state"].astext == "open",
        )
        .order_by(IngestedGitHubActivity.occurred_at.desc())
        .limit(200)
    )
    return list((await db.execute(stmt)).scalars().all())


# ── Singletons ─────────────────────────────────────────────────────


@router.get("/briefing", summary="Daily briefing")
async def get_briefing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        token = await get_valid_google_token(current_user.id, db)
    except TokenUnavailableError:
        today = datetime.now(timezone.utc)
        return {
            "data": {
                "greeting": "Hello",
                "date": f"{today:%A}, {today.day} {today:%B}",
                "summary": (
                    "Connect Google Calendar and Gmail on the Integrations page "
                    "to see your day here."
                ),
            }
        }

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
async def get_focus(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    github = await _github_rows(db, current_user.id)
    return {"data": live.build_focus(github)}


@router.get("/weather", summary="Current weather")
async def get_weather(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Integration).where(
        Integration.user_id == current_user.id,
        Integration.slug == "open_meteo",
        Integration.status == "connected",
    )
    integration = (await db.execute(stmt)).scalar_one_or_none()
    if integration is None:
        return {
            "data": {
                "temp": "—",
                "condition": "Connect Open-Meteo in Integrations",
                "city": "",
            }
        }
    cfg = integration.config or {}
    lat, lon = cfg.get("latitude"), cfg.get("longitude")
    if lat is None or lon is None:
        return {
            "data": {
                "temp": "—",
                "condition": "Set a location for Open-Meteo",
                "city": "",
            }
        }
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return {
            "data": {
                "temp": "—",
                "condition": "Open-Meteo location is invalid",
                "city": "",
            }
        }
    city = cfg.get("city") or f"{lat_f:.2f}, {lon_f:.2f}"
    try:
        data = await ambient.fetch_weather(lat_f, lon_f, city)
    except ambient.AmbientUnavailable as exc:
        logger.warning("Live weather unavailable (%s)", exc)
        data = {"temp": "—", "condition": "Weather unavailable right now", "city": city}
    return {"data": data}


@router.get("/commute", summary="Current commute")
async def get_commute():
    # No commute-time integration exists yet; say so instead of inventing an ETA.
    return {"data": {"eta": "—", "mode": "", "dest": "Not connected"}}


# ── Collections ────────────────────────────────────────────────────


@router.get("/tasks", summary="Open work across GitHub and Gmail")
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    github = await _github_rows(db, current_user.id)
    items = live.build_tasks(github)
    return {
        "data": [
            s.TaskResponse.model_validate(i).model_dump(by_alias=True) for i in items
        ],
        "total": len(items),
    }


@router.get("/events", summary="Events across calendars")
async def list_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        token = await get_valid_google_token(current_user.id, db)
    except TokenUnavailableError:
        return {"data": [], "total": 0}

    try:
        events = await fetch_todays_events(token)
    except Exception as exc:
        logger.warning("Live calendar fetch failed (%s)", exc, exc_info=True)
        return {"data": [], "total": 0}

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
async def list_decisions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    github = await _github_rows(db, current_user.id)
    items = live.build_decisions(github)
    return {
        "data": [
            s.DecisionResponse.model_validate(i).model_dump(by_alias=True)
            for i in items
        ],
        "total": len(items),
    }


@router.get("/agent-activity", summary="Recent agent runs")
async def list_agent_activity(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # AgentUsageLog has no user_id, so attribute runs through the chat
    # session they belong to; runs with no session are not shown.
    stmt = (
        select(AgentUsageLog)
        .join(ConversationSession, ConversationSession.id == AgentUsageLog.session_id)
        .where(ConversationSession.user_id == current_user.id)
        .order_by(AgentUsageLog.invoked_at.desc())
        .limit(8)
    )
    logs = list((await db.execute(stmt)).scalars().all())
    items = live.build_agent_activity(logs)
    return {
        "data": [
            s.AgentTickResponse.model_validate(i).model_dump(by_alias=True)
            for i in items
        ],
        "total": len(items),
    }


@router.get("/notifications", summary="Integration problems needing attention")
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Integration).where(Integration.user_id == current_user.id)
    integrations = list((await db.execute(stmt)).scalars().all())
    items = live.build_notifications(integrations)
    return {
        "data": [
            s.NotificationResponse.model_validate(i).model_dump(by_alias=True)
            for i in items
        ],
        "total": len(items),
    }


@router.get("/news", summary="Top Hacker News headlines")
async def list_news():
    try:
        items = await ambient.fetch_news()
    except ambient.AmbientUnavailable as exc:
        logger.warning("Live news unavailable (%s)", exc)
        items = []
    return {
        "data": [
            s.NewsResponse.model_validate(i).model_dump(by_alias=True) for i in items
        ],
        "total": len(items),
    }


@router.get("/quick-actions", summary="Quick action shortcuts")
async def list_quick_actions(db: AsyncSession = Depends(get_db)):
    items = (
        (await db.execute(select(m.QuickAction).order_by(m.QuickAction.id)))
        .scalars()
        .all()
    )
    return _collection(items, s.QuickActionResponse)


async def _read_json_route(route, current_user: User, db: AsyncSession, label: str):
    """Reuse a sibling route's logic; one failing source never blanks the card."""
    try:
        response = await route(current_user=current_user, db=db)
        return json.loads(response.body).get("data")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s unavailable for health habits (%s)", label, exc, exc_info=True
        )
        return None


@router.get(
    "/health-habits", summary="Health and habit metrics from Whoop / Apple Health"
)
async def list_health_habits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from src.api.v1 import apple_health, whoop

    whoop_data = await _read_json_route(whoop.get_dashboard, current_user, db, "Whoop")
    apple_data = await _read_json_route(
        apple_health.get_dashboard, current_user, db, "Apple Health"
    )
    items = live.build_health_habits(whoop_data, apple_data)
    return {
        "data": [
            s.HealthHabitResponse.model_validate(i).model_dump(by_alias=True)
            for i in items
        ],
        "total": len(items),
    }


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
