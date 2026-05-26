"""Read-only dashboard endpoints — Phase A.

Every collection returns ``{"data": [...], "total": N}``; every
singleton returns ``{"data": {...}}`` per ``.claude/rules/api.md``.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models import dashboard as m
from src.models.database import get_db
from src.schemas import dashboard as s

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


# Helper: shape collection responses
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
async def get_briefing(db: AsyncSession = Depends(get_db)):
    obj = (await db.execute(select(m.DailyBriefing).limit(1))).scalar_one_or_none()
    return _singleton(obj, s.DailyBriefingResponse, "briefing")


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
async def list_events(db: AsyncSession = Depends(get_db)):
    items = (await db.execute(select(m.Event).order_by(m.Event.id))).scalars().all()
    return _collection(items, s.EventResponse)


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
    # Frontend consumes only the text — return a list of strings.
    return {"data": [i.text for i in items], "total": len(items)}
