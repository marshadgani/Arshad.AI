"""Apple Health push-ingest + dashboard read endpoints.

POST /api/v1/apple-health/ingest
    Called by the user's iOS Shortcut, not the frontend. Auth is the
    ingest bearer token minted by AppleHealthIntegration.connect() — NOT
    the app's JWT, since a Shortcut can't hold a session that expires
    every JWT_EXPIRY_HOURS. Looked up by SHA-256 hash against
    integration_ingest_tokens; the cleartext token is never stored or
    logged anywhere past this comparison.

GET /api/v1/apple-health/dashboard
    Called by the frontend with the normal JWT. Reads the Redis-cached
    snapshot the most recent ingest wrote — see snapshot_cache_key() in
    integrations/personal/apple_health.py. Never reads Postgres for
    biometric values because none are ever written there.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.errors import http_error
from src.auth.dependencies import get_current_user
from src.middleware.cache import get_redis
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import Integration, IntegrationIngestToken
from src.models.user import User
from src.schemas.apple_health import (
    AppleHealthIngestPayload,
    AppleHealthSnapshot,
)
from src.services.apple_health import (
    CACHE_TTL_SECONDS,
    hash_ingest_token,
    snapshot_cache_key,
)

router = APIRouter(prefix="/api/v1/apple-health", tags=["apple-health"])

APPLE_HEALTH_SLUG = "apple_health"

# 20 pushes/hour per integration. A Shortcut running hourly, or even every
# 15 minutes, is nowhere near this; the limit exists to bound damage from a
# misconfigured Shortcut looping.
_INGEST_RATE_LIMIT = 20
_INGEST_RATE_WINDOW_SECONDS = 3600


async def _check_ingest_rate_limit(integration_id: str) -> None:
    await enforce_rate_limit(
        bucket="apple_health_ingest",
        identity=integration_id,
        limit=_INGEST_RATE_LIMIT,
        window_seconds=_INGEST_RATE_WINDOW_SECONDS,
        message="Too many ingest requests. Retry after 1 hour.",
    )


async def _authenticate_ingest_token(
    authorization: str | None, db: AsyncSession
) -> tuple[Integration, IntegrationIngestToken]:
    """Resolve the Integration an inbound push belongs to, from its bearer
    token, or raise 401.

    The presented token is re-hashed and matched against the stored digest;
    the cleartext value is never stored or logged anywhere past this
    comparison. Every failure returns the same generic 401 code so the
    response cannot be used to distinguish "no such token" from "revoked"
    from "integration disconnected".
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise http_error(
            401, "missing_ingest_token", "Authorization: Bearer <token> is required."
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise http_error(401, "missing_ingest_token", "Ingest token was empty.")

    token_row = await db.scalar(
        select(IntegrationIngestToken).where(
            IntegrationIngestToken.token_hash == hash_ingest_token(token),
            IntegrationIngestToken.revoked_at.is_(None),
        )
    )
    if token_row is None:
        raise http_error(
            401, "invalid_ingest_token", "Ingest token is invalid or revoked."
        )

    integration = await db.scalar(
        select(Integration).where(Integration.id == token_row.integration_id)
    )
    if integration is None or integration.status == "disconnected":
        raise http_error(401, "invalid_ingest_token", "Integration is disconnected.")

    return integration, token_row


@router.post("/ingest", summary="Receive a push from the Apple Health Shortcut")
async def ingest(
    payload: AppleHealthIngestPayload,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    integration, token_row = await _authenticate_ingest_token(authorization, db)
    await _check_ingest_rate_limit(str(integration.id))

    now = datetime.now(timezone.utc)
    snapshot = AppleHealthSnapshot(
        connected=True,
        resting_heart_rate=payload.resting_heart_rate,
        heart_rate_variability_ms=payload.heart_rate_variability_ms,
        sleep_hours=payload.sleep_hours,
        active_energy_kcal=payload.active_energy_kcal,
        steps=payload.steps,
        vo2_max=payload.vo2_max,
        recorded_at=payload.recorded_at,
        received_at=now.isoformat(),
    )

    # This is the ONLY write path for biometric values in this feature,
    # and it deliberately targets Redis with a TTL, never Postgres — see
    # the HUMAN REVIEW FLAG in integrations/personal/apple_health.py.
    redis_client = await get_redis()
    await redis_client.set(
        snapshot_cache_key(str(integration.id)),
        snapshot.model_dump_json(),
        ex=CACHE_TTL_SECONDS,
    )

    token_row.last_used_at = now
    integration.last_synced_at = now
    integration.last_error = None
    integration.status = "connected"
    await db.commit()

    return JSONResponse({"data": {"received": True}})


@router.get("/dashboard", summary="Latest cached Apple Health snapshot")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    integration = await db.scalar(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.slug == APPLE_HEALTH_SLUG,
            Integration.status != "disconnected",
        )
    )
    if integration is None:
        return JSONResponse({"data": AppleHealthSnapshot(connected=False).model_dump()})

    redis_client = await get_redis()
    cached = await redis_client.get(snapshot_cache_key(str(integration.id)))
    if not cached:
        return JSONResponse(
            {"data": AppleHealthSnapshot(connected=True, stale=True).model_dump()}
        )

    if isinstance(cached, bytes):
        cached = cached.decode("utf-8")
    snapshot = AppleHealthSnapshot.model_validate_json(cached)
    return JSONResponse({"data": snapshot.model_dump()})
