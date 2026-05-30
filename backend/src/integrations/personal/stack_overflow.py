"""Stack Overflow / Stack Exchange — public API with optional access token.

Uses the per-user paste-a-token model (personal_apikey). Requires:
  - The user's site (default 'stackoverflow') and user_id
  - Optional access token for higher rate limits / private data

Probe: GET /me/sites?key=APP_KEY&access_token=USER_TOKEN
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import decrypt
from ...models.integration import ApiKeyCredential, Integration
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from ..project._shared import (
    mark_error,
    mark_synced,
    project_status,
    require_api_key,
    store_api_key,
)
from ..registry import register

_API = "https://api.stackexchange.com/2.3"


@register
class StackOverflowIntegration(IntegrationProvider):
    slug = "stack_overflow"
    kind = "personal_apikey"
    display_name = "Stack Overflow"
    category = "Code"
    description = "Reputation, recent answers, top tags."
    docs_url = "https://api.stackexchange.com/docs"
    icon = "stackoverflow"

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        access_token = require_api_key(payload)
        site = (payload or {}).get("site", "stackoverflow")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_API}/me",
                    params={"site": site, "access_token": access_token},
                )
            if resp.status_code in (401, 403):
                raise IntegrationError(
                    "invalid_key", "Stack Exchange rejected the access token."
                )
            resp.raise_for_status()
            body = resp.json() or {}
        except IntegrationError:
            raise
        except httpx.HTTPError as exc:
            raise IntegrationError(
                "probe_failed", f"Stack Exchange unreachable: {type(exc).__name__}"
            )
        items = body.get("items") or []
        profile = items[0] if items else {}
        return await store_api_key(
            db=db,
            slug=self.slug,
            api_key=access_token,
            extra={
                "site": site,
                "user_id": profile.get("user_id"),
                "display_name": profile.get("display_name"),
                "reputation": profile.get("reputation"),
            },
            scopes=["read_inbox", "private_info"],
            user_id=user.id,
            kind="personal_apikey",
        )

    async def sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        creds = await db.scalar(
            select(ApiKeyCredential).where(
                ApiKeyCredential.integration_id == integration.id
            )
        )
        if creds is None:
            raise IntegrationError(
                "not_connected", "Stack Overflow access token not stored."
            )
        access_token = decrypt(creds.encrypted_key)
        site = (creds.extra or {}).get("site", "stackoverflow")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_API}/me",
                    params={"site": site, "access_token": access_token},
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            await mark_error(integration=integration, db=db, err=exc)
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        items = body.get("items") or []
        profile = items[0] if items else {}
        integration.config = {
            "site": site,
            "user_id": profile.get("user_id"),
            "display_name": profile.get("display_name"),
            "reputation": profile.get("reputation"),
            "answer_count": profile.get("answer_count"),
            "question_count": profile.get("question_count"),
        }
        return await mark_synced(
            integration=integration,
            db=db,
            summary=f"Stack Overflow: rep {profile.get('reputation', 0):,}",
            started=started,
        )

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        return await project_status(integration=integration, db=db)
