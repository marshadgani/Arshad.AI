"""AI Ecosystem API — agent registry and usage metrics.

Endpoints:
  GET  /api/v1/ai-ecosystem/agents          list all agents with live status
  GET  /api/v1/ai-ecosystem/metrics         usage metrics aggregated by period
  POST /api/v1/ai-ecosystem/log             record one agent invocation
  GET  /api/v1/ai-ecosystem/summary         aggregate totals for the period
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models.ai_ecosystem import AgentRegistry, AgentUsageLog
from src.models.database import get_db
from src.schemas.ai_ecosystem import (
    AgentMetricResponse,
    AgentResponse,
    LogRequest,
    SummaryResponse,
)

router = APIRouter(
    prefix="/api/v1/ai-ecosystem",
    tags=["ai-ecosystem"],
    dependencies=[Depends(get_current_user)],
)

Period = Literal["1h", "1d", "1w", "1m", "1y"]

_PERIOD_DELTA: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "1m": timedelta(days=30),
    "1y": timedelta(days=365),
}


def _cutoff(period: str) -> datetime:
    return datetime.now(timezone.utc) - _PERIOD_DELTA[period]


@router.get("/agents", summary="List all agents with live status")
async def list_agents(db: AsyncSession = Depends(get_db)) -> dict:
    agents = (
        (
            await db.execute(
                select(AgentRegistry).order_by(
                    AgentRegistry.pipeline_stage.nulls_last(),
                    AgentRegistry.display_name,
                )
            )
        )
        .scalars()
        .all()
    )

    # Determine ACTIVE/IDLE based on usage in last 24 hours
    active_names: set[str] = set()
    if agents:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        rows = (
            (
                await db.execute(
                    select(AgentUsageLog.agent_name)
                    .where(AgentUsageLog.invoked_at >= since)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        active_names = set(rows)

    result = []
    for a in agents:
        status = "ACTIVE" if a.agent_name in active_names else "IDLE"
        row = AgentResponse.model_validate(a)
        result.append({**row.model_dump(), "status": status})

    return {"data": result, "total": len(result)}


@router.get("/metrics", summary="Usage metrics aggregated by time period")
async def get_metrics(
    period: Period = Query(default="1d"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    since = _cutoff(period)

    rows = (
        await db.execute(
            select(
                AgentUsageLog.agent_name,
                func.count(AgentUsageLog.id).label("usage_count"),
                func.coalesce(func.sum(AgentUsageLog.tokens_used), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.avg(AgentUsageLog.tokens_used), 0).label(
                    "avg_tokens"
                ),
                func.avg(cast(AgentUsageLog.success, Float)).label("success_rate"),
            )
            .where(AgentUsageLog.invoked_at >= since)
            .group_by(AgentUsageLog.agent_name)
        )
    ).all()

    # Compute efficiency score relative to group average (lower tokens/use = better)
    metrics_raw = [
        {
            "agent_name": r.agent_name,
            "usage_count": r.usage_count,
            "total_tokens": int(r.total_tokens),
            "avg_tokens_per_use": int(r.avg_tokens),
            "success_rate": float(r.success_rate or 1.0),
        }
        for r in rows
    ]

    avg_tokens = (
        sum(m["avg_tokens_per_use"] for m in metrics_raw) / len(metrics_raw)
        if metrics_raw
        else 1
    )

    agents_out = []
    for m in metrics_raw:
        # Efficiency: 100 if tokens/use == 0, scales down as tokens increase vs avg
        if avg_tokens > 0 and m["avg_tokens_per_use"] > 0:
            ratio = avg_tokens / m["avg_tokens_per_use"]
            score = min(100, max(0, int(ratio * 100)))
        else:
            score = 100
        agents_out.append(
            AgentMetricResponse(
                agent_name=m["agent_name"],
                usage_count=m["usage_count"],
                total_tokens=m["total_tokens"],
                avg_tokens_per_use=m["avg_tokens_per_use"],
                success_rate=m["success_rate"],
                efficiency_score=score,
            ).model_dump()
        )

    return {"data": {"period": period, "agents": agents_out}}


@router.post("/log", summary="Record one agent invocation", status_code=201)
async def log_invocation(
    body: LogRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = AgentUsageLog(
        id=uuid.uuid4(),
        agent_name=body.agent_name,
        model=body.model,
        tokens_used=body.tokens_used,
        duration_ms=body.duration_ms,
        success=body.success,
        session_id=body.session_id,
        invoked_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.commit()
    return {"data": {"id": str(entry.id)}}


@router.get("/summary", summary="Aggregate stats for a time period")
async def get_summary(
    period: Period = Query(default="1d"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    since = _cutoff(period)

    total_rows = (
        await db.execute(
            select(
                func.count(AgentUsageLog.id).label("invocations"),
                func.coalesce(func.sum(AgentUsageLog.tokens_used), 0).label("tokens"),
            ).where(AgentUsageLog.invoked_at >= since)
        )
    ).one()

    # Most used agent
    most_used_row = (
        await db.execute(
            select(AgentUsageLog.agent_name, func.count(AgentUsageLog.id).label("cnt"))
            .where(AgentUsageLog.invoked_at >= since)
            .group_by(AgentUsageLog.agent_name)
            .order_by(func.count(AgentUsageLog.id).desc())
            .limit(1)
        )
    ).first()

    # Most efficient = lowest avg tokens per invocation (min 1 use)
    efficient_row = (
        await db.execute(
            select(
                AgentUsageLog.agent_name,
                func.avg(AgentUsageLog.tokens_used).label("avg_t"),
            )
            .where(AgentUsageLog.invoked_at >= since)
            .group_by(AgentUsageLog.agent_name)
            .having(func.count(AgentUsageLog.id) >= 1)
            .order_by(func.avg(AgentUsageLog.tokens_used).asc())
            .limit(1)
        )
    ).first()

    return {
        "data": SummaryResponse(
            period=period,
            total_invocations=int(total_rows.invocations),
            total_tokens=int(total_rows.tokens),
            most_used_agent=most_used_row.agent_name if most_used_row else None,
            most_efficient_agent=efficient_row.agent_name if efficient_row else None,
        ).model_dump()
    }
