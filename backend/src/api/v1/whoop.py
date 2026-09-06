"""Whoop health data endpoints.

Fetches live data from the Whoop Developer API using the stored OAuth token.
All endpoints require the user to have connected their Whoop account first.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.middleware.cache import get_redis
from src.models.database import get_db
from src.models.integration import Integration
from src.schemas.whoop import (
    WhoopDashboard,
    WhoopHRVPoint,
    WhoopRecovery,
    WhoopSleep,
    WhoopStrain,
    WhoopWorkout,
)

router = APIRouter(prefix="/api/v1/whoop", tags=["whoop"])

_BASE = "https://api.prod.whoop.com/developer/v1"

_SPORT_NAMES: dict[int, str] = {
    -1: "Activity",
    0: "Running",
    1: "Cycling",
    16: "Baseball",
    17: "Basketball",
    18: "Rowing",
    19: "Fencing",
    20: "Field Hockey",
    21: "Football",
    22: "Golf",
    24: "Ice Hockey",
    25: "Lacrosse",
    27: "Rugby",
    28: "Sailing",
    29: "Skiing",
    30: "Soccer",
    31: "Softball",
    32: "Squash",
    33: "Swimming",
    34: "Tennis",
    35: "Track & Field",
    36: "Volleyball",
    37: "Water Polo",
    38: "Wrestling",
    39: "Boxing",
    42: "Dance",
    43: "Pilates",
    44: "Yoga",
    45: "Weightlifting",
    47: "Cross Country Skiing",
    48: "Functional Fitness",
    49: "Duathlon",
    51: "Gymnastics",
    52: "Hiking/Rucking",
    53: "Horseback Riding",
    55: "Kayaking",
    56: "Martial Arts",
    57: "Mountain Biking",
    58: "Powerlifting",
    59: "Rock Climbing",
    60: "Paddleboarding",
    61: "Triathlon",
    62: "Walking",
    63: "Surfing",
    64: "Elliptical",
    65: "Stairmaster",
    67: "Meditation",
    68: "Other",
    71: "Duathlon",
    73: "Pickleball",
    74: "Hyrox",
}


async def _check_rate_limit(user_id: str) -> None:
    """Sliding-window 30 req/min per user across all Whoop endpoints."""
    redis = await get_redis()
    if redis is None:
        return
    key = f"rl:whoop:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    if count > 30:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Too many requests. Retry after 60 seconds.",
                    "details": {"retry_after": 60},
                }
            },
            headers={"Retry-After": "60"},
        )


async def _get_whoop_integration(user_id: str, db: AsyncSession) -> Integration | None:
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.slug == "whoop",
            Integration.status == "connected",
        )
    )
    return result.scalar_one_or_none()


async def _whoop_get(path: str, access_token: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()


async def _get_token(integration: Integration, db: AsyncSession) -> str:
    from src.integrations.personal.oauth_providers import WhoopIntegration

    return await WhoopIntegration().get_access_token(integration=integration, db=db)


def _parse_recovery(record: dict) -> WhoopRecovery:
    score = record.get("score") or {}
    return WhoopRecovery(
        recovery_score=score.get("recovery_score"),
        hrv_rmssd_milli=score.get("hrv_rmssd_milli"),
        resting_heart_rate=score.get("resting_heart_rate"),
        skin_temp_celsius=score.get("skin_temp_celsius"),
        spo2_percentage=score.get("spo2_percentage"),
        cycle_id=record.get("cycle_id"),
        created_at=record.get("created_at"),
    )


def _parse_sleep(record: dict) -> WhoopSleep:
    score = record.get("score") or {}
    stage = (score or {}).get("stage_summary") or {}
    return WhoopSleep(
        id=record.get("id"),
        start=record.get("start"),
        end=record.get("end"),
        total_in_bed_time_milli=stage.get("total_in_bed_time_milli"),
        total_awake_time_milli=stage.get("total_awake_time_milli"),
        total_no_data_time_milli=stage.get("total_no_data_time_milli"),
        total_light_sleep_time_milli=stage.get("total_light_sleep_time_milli"),
        total_slow_wave_sleep_time_milli=stage.get("total_slow_wave_sleep_time_milli"),
        total_rem_sleep_time_milli=stage.get("total_rem_sleep_time_milli"),
        sleep_performance_percentage=score.get("sleep_performance_percentage"),
        sleep_consistency_percentage=score.get("sleep_consistency_percentage"),
        sleep_efficiency_percentage=score.get("sleep_efficiency_percentage"),
        respiratory_rate=score.get("respiratory_rate"),
    )


def _parse_strain(record: dict) -> WhoopStrain:
    score = record.get("score") or {}
    return WhoopStrain(
        id=record.get("id"),
        start=record.get("start"),
        end=record.get("end"),
        score=score.get("strain"),
        kilojoule=score.get("kilojoule"),
        average_heart_rate=score.get("average_heart_rate"),
        max_heart_rate=score.get("max_heart_rate"),
    )


@router.get("/dashboard")
async def get_dashboard(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return today's recovery, sleep, and strain snapshot."""
    await _check_rate_limit(str(current_user.id))
    integration = await _get_whoop_integration(str(current_user.id), db)
    if not integration:
        return JSONResponse({"data": WhoopDashboard(connected=False).model_dump()})

    try:
        token = await _get_token(integration, db)
        recovery_body, sleep_body, strain_body = await _fetch_dashboard_data(token)
    except httpx.HTTPStatusError:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "whoop_api_error",
                    "message": "Upstream health service is unavailable. Please try again later.",
                    "details": {},
                }
            },
        )

    recovery_records = recovery_body.get("records") or []
    sleep_records = sleep_body.get("records") or []
    strain_records = strain_body.get("records") or []

    config = integration.config or {}
    dashboard = WhoopDashboard(
        connected=True,
        recovery=_parse_recovery(recovery_records[0]) if recovery_records else None,
        sleep=_parse_sleep(sleep_records[0]) if sleep_records else None,
        strain=_parse_strain(strain_records[0]) if strain_records else None,
        user_first_name=config.get("first_name"),
    )
    return JSONResponse({"data": dashboard.model_dump()})


async def _fetch_dashboard_data(token: str) -> tuple[Any, Any, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        recovery_resp, sleep_resp, strain_resp = await _parallel_get(
            client,
            headers,
            ["/recovery", "/sleep", "/cycle"],
            [{"limit": 1}, {"limit": 1}, {"limit": 1}],
        )
    return recovery_resp, sleep_resp, strain_resp


async def _parallel_get(
    client: httpx.AsyncClient,
    headers: dict,
    paths: list[str],
    params_list: list[dict],
) -> list[Any]:
    import asyncio

    async def fetch(path: str, params: dict) -> Any:
        resp = await client.get(f"{_BASE}{path}", headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    return await asyncio.gather(*[fetch(p, q) for p, q in zip(paths, params_list)])


@router.get("/hrv-trend")
async def get_hrv_trend(
    days: int = Query(default=14, ge=1, le=30),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return HRV data points for the last N days (max 30)."""
    await _check_rate_limit(str(current_user.id))
    integration = await _get_whoop_integration(str(current_user.id), db)
    if not integration:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "whoop_not_connected",
                    "message": "Whoop account not connected.",
                    "details": {},
                }
            },
        )

    from datetime import date, timedelta

    token = await _get_token(integration, db)
    start = (date.today() - timedelta(days=days)).isoformat()
    body = await _whoop_get("/recovery", token, {"limit": days, "start": start})
    records = body.get("records") or []

    points = [
        WhoopHRVPoint(
            date=r.get("created_at", "")[:10],
            hrv_rmssd_milli=(r.get("score") or {}).get("hrv_rmssd_milli"),
        ).model_dump()
        for r in reversed(records)
        if r.get("created_at")
    ]
    return JSONResponse({"data": points, "total": len(points)})


@router.get("/workouts")
async def get_workouts(
    limit: int = Query(default=10, ge=1, le=25),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return recent workouts."""
    await _check_rate_limit(str(current_user.id))
    integration = await _get_whoop_integration(str(current_user.id), db)
    if not integration:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "whoop_not_connected",
                    "message": "Whoop account not connected.",
                    "details": {},
                }
            },
        )

    token = await _get_token(integration, db)
    body = await _whoop_get("/workout", token, {"limit": limit})
    records = body.get("records") or []

    workouts = [
        WhoopWorkout(
            id=r.get("id"),
            sport_id=r.get("sport_id"),
            sport_name=_SPORT_NAMES.get(r.get("sport_id", -1), "Activity"),
            start=r.get("start"),
            end=r.get("end"),
            strain=(r.get("score") or {}).get("strain"),
            average_heart_rate=(r.get("score") or {}).get("average_heart_rate"),
            max_heart_rate=(r.get("score") or {}).get("max_heart_rate"),
            kilojoule=(r.get("score") or {}).get("kilojoule"),
        ).model_dump()
        for r in records
    ]
    return JSONResponse({"data": workouts, "total": len(workouts)})
