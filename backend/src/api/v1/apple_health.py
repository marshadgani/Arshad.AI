"""Apple Health push-ingest + dashboard read endpoints.

POST /api/v1/apple-health/ingest
    Called by the user's iOS Shortcut, not the frontend. Auth is the
    ingest bearer token minted by AppleHealthIntegration.connect() — NOT
    the app's JWT, since a Shortcut can't hold a session that expires
    every JWT_EXPIRY_HOURS. The rule itself lives in
    services/apple_health/ingest_auth.py.

GET /api/v1/apple-health/dashboard
    Called by the frontend with the normal JWT. Reads the snapshot the
    most recent ingest wrote, via services/apple_health/snapshot_store.py.
    Never reads Postgres for biometric values because none are ever
    written there.

This module is routing and wire shape only. The work it coordinates lives
in src/services/apple_health/: token verification in ingest_auth.py,
storage in snapshot_store.py, encryption in envelope.py. It keeps
`get_redis` as a module-level name on purpose — the router owns client
acquisition so the store stays a pure function of its arguments and the
seam remains substitutable from a test.

Both endpoints are fail-open toward Redis: a Redis outage never turns
into a 500 on the always-visible dashboard endpoint, and never marks an
ingest as "synced" when nothing was actually stored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import redis.exceptions
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.errors import http_error
from src.auth.dependencies import get_current_user
from src.middleware.cache import get_redis
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.integration import Integration
from src.models.user import User
from src.schemas.apple_health import AppleHealthIngestPayload, AppleHealthSnapshot
from src.services.apple_health import ingest_auth, snapshot_store

_log = logging.getLogger(__name__)

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


def _snapshot_response(snapshot: AppleHealthSnapshot) -> JSONResponse:
    return JSONResponse({"data": snapshot.model_dump(mode="json")})


@router.post("/ingest", summary="Receive a push from the Apple Health Shortcut")
async def ingest(
    payload: AppleHealthIngestPayload,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    integration, token_row = await ingest_auth.authenticate(authorization, db)
    await _check_ingest_rate_limit(str(integration.id))

    now = datetime.now(timezone.utc)
    snapshot = AppleHealthSnapshot.from_ingest(payload, received_at=now)

    # This is the ONLY write path for biometric values in this feature. It
    # targets Redis with a TTL, never Postgres — see the HUMAN REVIEW FLAG
    # in integrations/personal/apple_health.py — and the value written is
    # AES-GCM ciphertext, never cleartext, so the "never persisted at rest
    # in cleartext" constraint holds regardless of Redis RDB/AOF config.
    redis_client = await get_redis()
    try:
        await snapshot_store.write(redis_client, str(integration.id), snapshot)
    except RuntimeError:
        _log.critical(
            "apple_health.ingest: encryption unavailable — "
            "OAUTH_ENCRYPTION_KEY missing or malformed"
        )
        raise http_error(
            500,
            "encryption_unavailable",
            "Health data encryption is not configured. Contact the app administrator.",
        ) from None
    except redis.exceptions.RedisError:
        _log.warning("apple_health.ingest: Redis unavailable — snapshot not stored")
        # Nothing was actually persisted, so don't mark the integration as
        # freshly synced — that would tell the dashboard a push landed when
        # it didn't.
        raise http_error(
            503,
            "cache_unavailable",
            "Health data store is temporarily unavailable. "
            "Your Shortcut will retry on its next run.",
        ) from None

    token_row.last_used_at = now
    integration.last_synced_at = now
    integration.last_error = None
    integration.status = "connected"
    await db.commit()

    return JSONResponse(
        {"data": {"received": True, "dropped_fields": payload.dropped_fields}}
    )


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
        return _snapshot_response(AppleHealthSnapshot(connected=False))

    redis_client = await get_redis()
    snapshot = await snapshot_store.load(redis_client, str(integration.id))
    if snapshot is None:
        # No push yet, TTL elapsed, Redis down, or a corrupt/foreign/
        # key-rotated value — one branch, never a 500. See
        # services/apple_health/snapshot_store.py::load.
        return _snapshot_response(AppleHealthSnapshot(connected=True, stale=True))

    return _snapshot_response(snapshot)
