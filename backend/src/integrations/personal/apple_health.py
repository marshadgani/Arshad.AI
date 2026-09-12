"""Apple Health integration — push-ingest via iOS Shortcut, not OAuth.

HealthKit has no cloud API: Apple never lets a server pull a user's health
data directly. The only realistic path is the user's own device pushing
exports out, so this provider is a "personal_push" kind (see base.py):

  1. connect() mints a one-time bearer token, stores only its SHA-256 hash
     (IntegrationIngestToken), and hands the cleartext token back exactly
     once via ConnectResult.ingest_token. The user pastes it into an iOS
     Shortcut (or the "Health Auto Export" app) that POSTs a JSON export
     to POST /api/v1/apple-health/ingest on a schedule they control.
  2. The ingest endpoint (api/v1/apple_health.py) authenticates that POST
     by re-hashing the presented token and looking up the hash — nothing
     here ever stores or logs the cleartext token again.
  3. Biometric values themselves (HR, HRV, sleep, steps, VO2max) are never
     written to Postgres, in cleartext or otherwise — same rule Whoop's
     sync() follows (see WhoopIntegration.sync docstring below in
     oauth_providers.py). The ingest endpoint caches the latest snapshot
     in Redis with a short TTL and nothing else persists it.

HUMAN REVIEW FLAG — MITIGATED, NOT CLOSED: unlike Whoop (server pulls
fresh data on every dashboard request, so "live" and "never at rest" are
the same thing), Apple Health is push-only — there is no pull to retry
between Shortcut runs. A short-TTL Redis cache is the closest analogue to
"live" available here.

  1. Snapshots are AES-GCM encrypted (src/auth/crypto.py) and
     base64-encoded before the Redis write (see
     services/apple_health/envelope.py). Redis RDB/AOF
     snapshotting to disk therefore stores only ciphertext, never
     cleartext biometric values.
  2. This narrows the residual exposure, it does not close it: the
     encryption key (OAUTH_ENCRYPTION_KEY) lives in the same process
     environment as the Redis client, so an attacker with both
     environment access AND disk access is unprotected. What encryption
     genuinely buys is protection against managed-Redis snapshot
     exfiltration WITHOUT environment access.
  3. Whether to additionally disable Redis persistence for defence in
     depth remains Arshad's decision — now a hardening choice rather than
     a correctness gate, but still open.
  4. Rotating OAUTH_ENCRYPTION_KEY renders every cached snapshot
     undecryptable. This is treated as a cache miss (stale=True), never
     an error, and self-heals within one TTL (6 hours) as the user's next
     Shortcut push writes a fresh snapshot under the new key.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any

import redis.exceptions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...middleware.cache import get_redis
from ...models.integration import Integration, IntegrationIngestToken
from ...models.user import User
from ...services.apple_health import snapshot_store
from ...services.apple_health.ingest_auth import hash_ingest_token
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from ..registry import register

_log = logging.getLogger(__name__)


@register
class AppleHealthIntegration(IntegrationProvider):
    slug = "apple_health"
    kind = "personal_push"
    display_name = "Apple Health"
    category = "Health"
    description = (
        "Push-based sync via an iOS Shortcut — HealthKit has no cloud API, "
        "so your phone sends data to us instead of us pulling it."
    )
    docs_url = "https://developer.apple.com/documentation/healthkit"
    icon = "apple-health"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")

        integration = await db.scalar(
            select(Integration).where(
                Integration.user_id == user.id, Integration.slug == self.slug
            )
        )
        if integration is None:
            integration = Integration(
                user_id=user.id,
                slug=self.slug,
                kind=self.kind,
                status="connected",
                config={},
            )
            db.add(integration)
            await db.flush()
        else:
            integration.status = "connected"
            integration.last_error = None

        token = secrets.token_urlsafe(32)
        token_hash = hash_ingest_token(token)

        # Rotate: one active token per integration (uq_ingest_token_one_
        # per_integration). Replacing the hash in place — rather than
        # inserting a second row — means a previously-issued token that
        # leaked stops authenticating the instant the user reconnects,
        # with no separate revoke step required.
        token_row = await db.scalar(
            select(IntegrationIngestToken).where(
                IntegrationIngestToken.integration_id == integration.id
            )
        )
        if token_row is None:
            token_row = IntegrationIngestToken(
                integration_id=integration.id, token_hash=token_hash
            )
            db.add(token_row)
        else:
            token_row.token_hash = token_hash
            token_row.revoked_at = None
            token_row.last_used_at = None

        await db.commit()
        await db.refresh(integration)

        return ConnectResult(
            integration_id=str(integration.id),
            redirect_url=None,
            ingest_token=token,
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        """There is nothing to pull — data only arrives via the ingest
        webhook. 'Sync' here just reports whether a recent push is on
        file, so the manual Sync button in the UI does something useful
        instead of erroring on a provider that works by push.
        """

        started = time.perf_counter()
        if await self._has_recent_push(integration):
            integration.last_error = None
            summary = (
                "Apple Health: last Shortcut push is still within the cache window."
            )
        else:
            summary = (
                "Apple Health: no recent data from your Shortcut. "
                "Check it's still running on your device."
            )
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=summary,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    async def _has_recent_push(integration: Integration) -> bool:
        """True when a snapshot is still in the cache window.

        Fails open, matching the rest of this feature (api/v1/apple_health.py,
        middleware/rate_limit.py): a Redis outage must degrade to "no recent
        push" rather than 500 the manual Sync button or flip the integration
        to `error` in the integrations list, which is what an escaping
        RedisError did here.
        """
        try:
            redis_client = await get_redis()
            return await snapshot_store.has_snapshot(redis_client, str(integration.id))
        except redis.exceptions.RedisError:
            _log.warning(
                "apple_health: Redis unavailable — reporting no recent push "
                "for integration %s",
                integration.id,
            )
            return False

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        has_cached_snapshot = await self._has_recent_push(integration)
        return StatusReport(
            status=integration.status,  # type: ignore[arg-type]
            last_synced_at=(
                integration.last_synced_at.isoformat()
                if integration.last_synced_at
                else None
            ),
            last_error=integration.last_error,
            extra={"has_recent_push": has_cached_snapshot},
        )

    async def disconnect(self, *, integration: Integration, db: AsyncSession) -> None:
        """Revoke the ingest token too — the default base implementation
        only flips integration.status, which would leave a still-valid
        bearer token able to keep authenticating POSTs after 'disconnect'.
        """
        token_row = await db.scalar(
            select(IntegrationIngestToken).where(
                IntegrationIngestToken.integration_id == integration.id
            )
        )
        if token_row is not None:
            token_row.revoked_at = datetime.now(timezone.utc)
        integration.status = "disconnected"
        integration.last_error = None
        await db.commit()
