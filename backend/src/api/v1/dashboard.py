"""Dashboard API endpoints — Phase A + live Google Calendar / Gmail / Claude data.

/events and /briefing serve live data when Google is connected, falling back to
seeded mock rows on TokenUnavailableError. /tasks, /agent-activity, /notifications
and /decisions derive rows from ingested Gmail/GitHub tables with the same seed
fallback. /weather serves live OpenWeatherMap conditions and is always HTTP 200,
rendering an empty tile with a Connect CTA when never connected (see
.claude/rules/api.md § Documented deviation). The remaining endpoints are
seed-only.

Every collection returns ``{"data": [...], "total": N}``; every singleton returns
``{"data": {...}}`` per ``.claude/rules/api.md``.

Layering: this module is transport only. Everything below the transport
boundary lives in the ``services/dashboard/`` package — ``queries`` fetches
ingested rows, ``projections`` turns a row into widget fields (over
``formatting``, ``rows`` and ``heuristics``). What remains here is route
wiring, the live→seed fallback policy, and response envelope construction.

The fallback policy stays here rather than moving into the service package
on purpose: it must keep the DB read *outside* its try/except so a real
infrastructure failure surfaces as a 500 instead of silently degrading to
seed rows. A single service call that fused "fetch" and "derive" would lose
that distinction.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models import dashboard as m
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.user import User
from src.schemas import dashboard as s
from src.services.briefing import compose_briefing
from src.services.dashboard import projections as derive
from src.services.dashboard import queries
from src.services.gmail_client import fetch_unread_count
from src.services.google_calendar import fetch_todays_events
from src.services.google_token import TokenUnavailableError, get_valid_google_token
from src.services.weather.service import get_weather_dashboard

# Where a hybrid widget's rows came from. Narrowed to the two values the
# frontend understands so a typo'd mode fails type-checking rather than
# reaching the client.
DashboardMode = Literal["live", "seed"]

logger = logging.getLogger(__name__)


def _no_store(response: Response) -> None:
    """Mark every dashboard response uncacheable.

    These payloads are per-user personal data derived from the caller's
    own Gmail subjects and GitHub PR/issue titles, yet they are plain
    authenticated GETs with no validator and no explicit freshness
    directive. RFC 9111 lets a cache store such a response heuristically,
    so a shared proxy/CDN in front of the API (or a shared browser
    profile) could serve one user's tasks, decisions or notifications to
    the next caller. ``no-store`` is the only directive that forbids
    writing the body to disk at all.

    Applied once at the router so a new dashboard route cannot forget it.
    """
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user), Depends(_no_store)],
)


async def _fetch_all(db: AsyncSession, stmt: Select[Any]) -> Sequence[Any]:
    """Every seed-table read in this module goes through here."""
    return (await db.execute(stmt)).scalars().all()


def _collection(
    items: Sequence[Any],
    schema: type[BaseModel],
    *,
    mode: DashboardMode | None = None,
) -> dict[str, Any]:
    """The one place a dashboard collection envelope is built.

    ``items`` may be ORM rows (seed tables) or the plain dicts produced by
    ``services/dashboard/projections`` — both are valid ``model_validate``
    inputs, so live and seed responses serialise identically.
    """
    result: dict[str, Any] = {
        "data": [schema.model_validate(i).model_dump(by_alias=True) for i in items],
        "total": len(items),
    }
    if mode is not None:
        result["mode"] = mode
    return result


async def _seed(
    db: AsyncSession,
    *,
    widget: str,
    schema: type[BaseModel],
    seed_stmt: Select[Any],
    reason: str,
) -> dict[str, Any]:
    """The one seed-mode response builder for the hybrid widgets.

    ``reason`` records *why* live data wasn't served, which is the only
    thing the seed branches ever differed by — a widget stuck on seed rows
    in production is diagnosable from the logs without re-reading this file.
    """
    items = await _fetch_all(db, seed_stmt)
    logger.info(
        "dashboard widget=%s mode=seed reason=%s count=%d", widget, reason, len(items)
    )
    return _collection(items, schema, mode="seed")


async def _live_or_seed(
    db: AsyncSession,
    *,
    widget: str,
    live_rows: Sequence[Any],
    derive_rows: Callable[[Sequence[Any]], Sequence[Any]],
    schema: type[BaseModel],
    seed_stmt: Select[Any],
) -> dict[str, Any]:
    """Shared live→seed fallback policy for the four hybrid widgets.

    Seed rows are served when there are no ingested rows, when derivation
    filters every row out (e.g. no critical-labelled issues), or when
    derivation raises. Derivation is a heuristic over untrusted third-party
    JSONB, so its failure degrades the widget to seed data rather than
    failing the request — the DB read itself is deliberately *not* wrapped,
    so a real infrastructure failure still surfaces as a 500.
    """
    rows: Sequence[Any] = ()
    reason = "no_ingested_rows"
    if live_rows:
        reason = "no_rows_derived"
        try:
            rows = derive_rows(live_rows)
        except Exception:  # noqa: BLE001 — heuristic, not core logic
            reason = "derivation_failed"
            logger.warning(
                "dashboard widget=%s derivation failed; falling back to seed",
                widget,
                exc_info=True,
            )
            rows = ()

    if rows:
        logger.info("dashboard widget=%s mode=live count=%d", widget, len(rows))
        return _collection(rows, schema, mode="live")

    return await _seed(
        db, widget=widget, schema=schema, seed_stmt=seed_stmt, reason=reason
    )


async def _singleton(
    db: AsyncSession, model: type[Any], schema: type[BaseModel], name: str
) -> dict[str, Any]:
    """Serve the single row of a seed singleton table, or 404 if unseeded."""
    obj = (await db.execute(select(model).limit(1))).scalar_one_or_none()
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
        return await _singleton(
            db, m.DailyBriefing, s.DailyBriefingResponse, "briefing"
        )

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
    return await _singleton(db, m.FocusBlock, s.FocusBlockResponse, "focus")


# Per-user cap on the weather tile, matching the Whoop/Shopify/Finance
# dashboards (api/v1/whoop.py, api/v1/shopify.py). This is the only
# dashboard route with third-party egress: a cache miss becomes one
# outbound OpenWeatherMap call, and the cache-eviction branch in
# services/weather/service.py deliberately forces a miss whenever the
# cached entry has no renderable temperature. Without a cap, a loop
# against this endpoint (or a stolen token) is amplified 1:1 into the
# user's OpenWeatherMap quota until the provider 429s and the tile
# degrades for everyone sharing the key.
_WEATHER_RATE_LIMIT = 30
_WEATHER_RATE_WINDOW_SECONDS = 60


@router.get("/weather", summary="Current weather")
async def get_weather(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live OpenWeatherMap current conditions when connected; an empty tile
    with a Connect CTA when never connected. Always HTTP 200 apart from a
    429 once the per-user rate limit is exceeded — see
    ``services/weather/service.get_weather_dashboard`` for the full
    decision tree.
    """
    await enforce_rate_limit(
        bucket="dashboard_weather",
        identity=str(current_user.id),
        limit=_WEATHER_RATE_LIMIT,
        window_seconds=_WEATHER_RATE_WINDOW_SECONDS,
        message=(
            "Too many weather requests. Retry after "
            f"{_WEATHER_RATE_WINDOW_SECONDS} seconds."
        ),
    )
    response = await get_weather_dashboard(current_user.id, db)
    return {"data": response.model_dump(by_alias=True)}


@router.get("/commute", summary="Current commute")
async def get_commute(db: AsyncSession = Depends(get_db)):
    return await _singleton(db, m.Commute, s.CommuteResponse, "commute")


# ── Collections ────────────────────────────────────────────────────


@router.get("/tasks", summary="Auto-prioritised tasks across sources")
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    live_rows = await queries.fetch_flagged_gmail_threads(db, current_user.id)
    return await _live_or_seed(
        db,
        widget="tasks",
        live_rows=live_rows,
        derive_rows=derive.derive_tasks_from_gmail,
        schema=s.TaskResponse,
        seed_stmt=select(m.Task).order_by(m.Task.priority, m.Task.id),
    )


@router.get("/events", summary="Events across calendars")
async def list_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    async def _seeded_events() -> dict[str, Any]:
        items = await _fetch_all(db, select(m.Event).order_by(m.Event.id))
        return _collection(items, s.EventResponse)

    try:
        token = await get_valid_google_token(current_user.id, db)
    except TokenUnavailableError:
        return await _seeded_events()

    try:
        events = await fetch_todays_events(token)
    except Exception as exc:
        logger.warning("Live calendar fetch failed (%s); falling back to mock", exc)
        return await _seeded_events()

    return {
        "data": [
            s.EventResponse.model_validate(asdict(e)).model_dump(by_alias=True)
            for e in events
        ],
        "total": len(events),
    }


@router.get("/agents", summary="Cross-domain agent roster")
async def list_agents(db: AsyncSession = Depends(get_db)):
    items = await _fetch_all(db, select(m.AgentGlobal).order_by(m.AgentGlobal.id))
    return _collection(items, s.AgentResponse)


@router.get("/decisions", summary="Decisions waiting on the user")
async def list_decisions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live GitHub PR rows (open, non-draft, user is requested reviewer or
    is the author with no outstanding review requests), falling back to
    seed rows when GitHub is unlinked, there are no ingested PRs, or every
    PR is filtered out.

    Short-circuits before the PR fetch when GitHub isn't linked — there is
    nothing to derive, so there is no reason to issue the read.
    """
    seed_stmt = select(m.Decision).order_by(m.Decision.id)
    github_user_id = await queries.fetch_github_provider_user_id(db, current_user.id)
    if github_user_id is None:
        return await _seed(
            db,
            widget="decisions",
            schema=s.DecisionResponse,
            seed_stmt=seed_stmt,
            reason="github_unlinked",
        )

    live_rows = await queries.fetch_github_activity_by_kind(db, current_user.id, "pr")
    return await _live_or_seed(
        db,
        widget="decisions",
        live_rows=live_rows,
        derive_rows=functools.partial(
            derive.derive_decisions_from_github, github_user_id=github_user_id
        ),
        schema=s.DecisionResponse,
        seed_stmt=seed_stmt,
    )


@router.get("/agent-activity", summary="Live agent ticker")
async def list_agent_activity(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    live_rows = await queries.fetch_github_activity_by_kind(db, current_user.id, "pr")
    return await _live_or_seed(
        db,
        widget="agent-activity",
        live_rows=live_rows,
        derive_rows=derive.derive_activities_from_github,
        schema=s.AgentTickResponse,
        seed_stmt=select(m.AgentTick).order_by(m.AgentTick.id),
    )


@router.get("/notifications", summary="Notifications")
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # derive_notifications_from_github further filters to critical/warn
    # labelled issues, so an empty derived list also triggers seed fallback.
    live_rows = await queries.fetch_github_activity_by_kind(
        db, current_user.id, "issue"
    )
    return await _live_or_seed(
        db,
        widget="notifications",
        live_rows=live_rows,
        derive_rows=derive.derive_notifications_from_github,
        schema=s.NotificationResponse,
        seed_stmt=select(m.Notification).order_by(m.Notification.id),
    )


@router.get("/github-activity", summary="Recent GitHub issues and PRs")
async def list_github_activity(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reads directly from ``ingested_github_activity`` — no live GitHub
    call. Deliberately no try/except around the query: a DB failure must
    surface as 500, never be masked as an empty card.

    Unlike the three hybrid widgets above there is no seed fallback, so this
    route does not go through ``_live_or_seed``: an empty feed is a truthful
    answer here, not a reason to show mock rows.
    """
    rows = await queries.fetch_recent_github_activity(db, current_user.id)
    projected = derive.derive_github_activity(rows)

    logger.info(
        "dashboard widget=github-activity count=%d skipped=%d",
        len(projected),
        len(rows) - len(projected),
    )
    return _collection(projected, s.GitHubActivityResponse)


@router.get("/news", summary="News headlines")
async def list_news(db: AsyncSession = Depends(get_db)):
    items = await _fetch_all(db, select(m.NewsItem).order_by(m.NewsItem.id))
    return _collection(items, s.NewsResponse)


@router.get("/quick-actions", summary="Quick action shortcuts")
async def list_quick_actions(db: AsyncSession = Depends(get_db)):
    items = await _fetch_all(db, select(m.QuickAction).order_by(m.QuickAction.id))
    return _collection(items, s.QuickActionResponse)


@router.get("/health-habits", summary="Health and habit metrics")
async def list_health_habits(db: AsyncSession = Depends(get_db)):
    items = await _fetch_all(db, select(m.HealthHabit).order_by(m.HealthHabit.name))
    return _collection(items, s.HealthHabitResponse)


@router.get("/knowledge-suggestions", summary="Knowledge-search suggestions")
async def list_knowledge_suggestions(db: AsyncSession = Depends(get_db)):
    items = await _fetch_all(
        db, select(m.KnowledgeSuggestion).order_by(m.KnowledgeSuggestion.text)
    )
    return {"data": [i.text for i in items], "total": len(items)}
