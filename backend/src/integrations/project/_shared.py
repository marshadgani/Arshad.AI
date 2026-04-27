"""Shared helpers for project_apikey integrations.

Pattern:
  1. connect() takes payload {"api_key": "...", "extra": {...}}
  2. Calls a probe (provider-specific) to validate the key
  3. Encrypts the key with the AES-GCM helper from auth.crypto
  4. Stores in api_key_credentials, integration row marked connected
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import encrypt
from ...models.integration import ApiKeyCredential, Integration
from ..base import (
    ConnectResult,
    IntegrationError,
    StatusReport,
    SyncResult,
)


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
) -> ConnectResult:
    """Project_apikey integrations are global to the deployment (user_id null).
    Replace any existing row for the slug."""
    integration = await db.scalar(
        select(Integration).where(
            Integration.user_id.is_(None), Integration.slug == slug
        )
    )
    if integration is None:
        integration = Integration(
            user_id=None,
            slug=slug,
            kind="project_apikey",
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
    creds = await db.scalar(
        select(ApiKeyCredential).where(
            ApiKeyCredential.integration_id == integration.id
        )
    )
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
    integration.status = "error"
    integration.last_error = f"{type(err).__name__}: {err}"[:500]
    await db.commit()


def require_api_key(payload: dict[str, Any]) -> str:
    api_key = (payload or {}).get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise IntegrationError(
            "missing_api_key", "Provide a non-empty 'api_key' in the request body."
        )
    return api_key.strip()
