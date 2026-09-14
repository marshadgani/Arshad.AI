"""Shared helpers for project_apikey integrations.

Pattern:
  1. connect() takes payload {"api_key": "...", "extra": {...}}
  2. Calls a probe (provider-specific) to validate the key
  3. Encrypts the key with the AES-GCM helper from auth.crypto
  4. Stores in api_key_credentials, integration row marked connected
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import TokenDecryptError, decrypt, encrypt
from ...models.integration import ApiKeyCredential, Integration
from ..base import (
    ConnectResult,
    IntegrationError,
    StatusReport,
    SyncResult,
    safe_detail,
)

_log = logging.getLogger(__name__)

# Key into AsyncSession.info (a plain per-session scratch dict SQLAlchemy
# guarantees exists) used to cache a batch-loaded credential lookup for
# the lifetime of one request. Populated by preload_api_key_credentials();
# read by _credential_for(). Without this, GET /api/v1/integrations issues
# one ApiKeyCredential query per registered provider (N+1 — ~20+ round
# trips on every page load, one per api-key provider in the registry) even
# though every request needs the exact same set of rows.
_CREDENTIAL_CACHE_KEY = "_api_key_credentials_by_integration"


async def preload_api_key_credentials(
    db: AsyncSession, integration_ids: list[uuid.UUID]
) -> None:
    """Batch-load ApiKeyCredential rows for a set of integrations into
    db.info, so subsequent load_api_key()/project_status() calls on the
    same session hit the cache instead of issuing their own query.

    Call once per request before fanning out over multiple providers (see
    routers.list_integrations). Safe to call with an empty list. Calling
    it more than once on the same session merges in any newly-requested
    ids rather than re-querying ones already cached.
    """
    cache: dict[uuid.UUID, ApiKeyCredential | None] = db.info.setdefault(
        _CREDENTIAL_CACHE_KEY, {}
    )
    missing = [i for i in integration_ids if i not in cache]
    if not missing:
        return
    rows = (
        await db.scalars(
            select(ApiKeyCredential).where(ApiKeyCredential.integration_id.in_(missing))
        )
    ).all()
    by_id = {row.integration_id: row for row in rows}
    for integration_id in missing:
        cache[integration_id] = by_id.get(integration_id)


async def _credential_for(
    integration_id: uuid.UUID, db: AsyncSession
) -> ApiKeyCredential | None:
    """The single read path for one integration's ApiKeyCredential row.

    Prefers the request-scoped cache populated by
    preload_api_key_credentials(); falls back to a direct query so every
    caller that hasn't preloaded (single-integration endpoints, sync(),
    connect()) keeps working unchanged."""
    cache: dict[uuid.UUID, ApiKeyCredential | None] | None = db.info.get(
        _CREDENTIAL_CACHE_KEY
    )
    if cache is not None and integration_id in cache:
        return cache[integration_id]
    return await db.scalar(
        select(ApiKeyCredential).where(
            ApiKeyCredential.integration_id == integration_id
        )
    )


async def load_api_key(
    *, integration: Integration, db: AsyncSession, display_name: str
) -> str:
    """Fetch and decrypt the stored API key, or raise IntegrationError.

    The single read path for a stored project API key, so the decrypt
    failure mode is handled once instead of being re-derived (and
    forgotten) at each provider.

    `decrypt` raises TokenDecryptError — a plain Exception — whenever the
    ciphertext is truncated, corrupt, or was sealed with a different
    OAUTH_ENCRYPTION_KEY. Key rotation is a documented, *expected*
    operational event (see CLAUDE.md §6: "Rotation locks all users out"),
    so it must not reach the router as an unhandled 500: the router only
    translates IntegrationError, and a 500 tells the user nothing they
    can act on. It is translated to `not_connected` — the same code used
    when no credential row exists at all — because the two are
    indistinguishable to the user and call for the identical remedy
    (reconnect the integration). Reusing an existing code keeps the
    machine-readable vocabulary closed rather than inventing one the
    frontend has never heard of.

    The underlying reason is deliberately not echoed to the client: it
    describes our ciphertext, not the user's problem. It is preserved as
    the `__cause__` for server-side logs.
    """
    creds = await _credential_for(integration.id, db)
    if creds is None:
        raise IntegrationError("not_connected", f"{display_name} key not stored.")
    try:
        return decrypt(creds.encrypted_key)
    except TokenDecryptError as exc:
        raise IntegrationError(
            "not_connected",
            f"Stored {display_name} key could not be read. Please reconnect.",
        ) from exc


def redact(key: str) -> str:
    if len(key) <= 6:
        return key[:2] + "***"
    return key[:6] + "***"


async def store_api_key(
    *,
    db: AsyncSession,
    slug: str,
    api_key: str,
    extra: dict[str, Any] | None = None,
    scopes: list[str] | None = None,
    user_id: Any = None,
    kind: str = "project_apikey",
) -> ConnectResult:
    """Store an API-key-based integration. Pass user_id for personal_apikey
    (per-user, e.g. Notion, Linear), leave None for project_apikey
    (deployment-wide, e.g. Render, Vercel)."""
    if user_id is None:
        clause = (Integration.user_id.is_(None)) & (Integration.slug == slug)
    else:
        clause = (Integration.user_id == user_id) & (Integration.slug == slug)
    integration = await db.scalar(select(Integration).where(clause))
    if integration is None:
        integration = Integration(
            user_id=user_id,
            slug=slug,
            kind=kind,
            status="connected",
            config={},
        )
        db.add(integration)
        await db.flush()

    creds = await db.scalar(
        select(ApiKeyCredential).where(
            ApiKeyCredential.integration_id == integration.id
        )
    )
    blob = encrypt(api_key)
    prefix = redact(api_key)
    if creds is None:
        creds = ApiKeyCredential(
            integration_id=integration.id,
            encrypted_key=blob,
            key_prefix=prefix,
            scopes=scopes or [],
            extra=extra or {},
        )
        db.add(creds)
    else:
        creds.encrypted_key = blob
        creds.key_prefix = prefix
        if scopes is not None:
            creds.scopes = scopes
        if extra is not None:
            creds.extra = extra
    integration.status = "connected"
    integration.last_error = None
    await db.commit()
    await db.refresh(integration)
    return ConnectResult(integration_id=str(integration.id), redirect_url=None)


async def project_status(
    *,
    integration: Integration,
    db: AsyncSession,
) -> StatusReport:
    creds = await _credential_for(integration.id, db)
    extra: dict[str, Any] = {}
    if creds is not None:
        extra["key_prefix"] = creds.key_prefix
        extra["scopes"] = list(creds.scopes or [])
        extra.update(creds.extra or {})
    return StatusReport(
        status=integration.status,  # type: ignore[arg-type]
        last_synced_at=(
            integration.last_synced_at.isoformat()
            if integration.last_synced_at
            else None
        ),
        last_error=integration.last_error,
        extra=extra,
    )


async def mark_synced(
    *, integration: Integration, db: AsyncSession, summary: str, started: float
) -> SyncResult:
    integration.last_synced_at = datetime.now(timezone.utc)
    integration.last_error = None
    integration.status = "connected"
    await db.commit()
    return SyncResult(
        rows_written=0,
        summary=summary,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


async def mark_error(
    *, integration: Integration, db: AsyncSession, err: Exception
) -> None:
    """Record a failed sync.

    `last_error` is returned verbatim to the client by
    GET /api/v1/integrations/{slug}/status, so it may only ever hold
    `safe_detail(err)` — never `str(err)`, which for an httpx error is the
    full request URL and therefore the plaintext API key of any provider
    that authenticates via the query string. The full exception is logged
    instead, where only the operator can read it.
    """
    _log.warning("sync failed for integration %s", integration.id, exc_info=err)
    integration.status = "error"
    integration.last_error = safe_detail(err)[:500]
    await db.commit()


def require_api_key(payload: dict[str, Any]) -> str:
    api_key = (payload or {}).get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise IntegrationError(
            "missing_api_key", "Provide a non-empty 'api_key' in the request body."
        )
    return api_key.strip()
