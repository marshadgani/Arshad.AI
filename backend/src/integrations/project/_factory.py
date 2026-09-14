"""Tiny factory for simple API-key providers — provider just declares
metadata + a probe URL/headers. Used for providers that don't need
custom sync logic beyond a status check.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
from sqlalchemy import select

from ...auth.crypto import decrypt
from ...models.integration import ApiKeyCredential
from ..base import (
    IntegrationError,
    IntegrationProvider,
)
from ..parse_guard import decode_json, guarded_parse
from ._shared import (
    mark_error,
    mark_synced,
    project_status,
    require_api_key,
    store_api_key,
)


@dataclass
class ProviderSpec:
    slug: str
    display_name: str
    category: str
    description: str
    docs_url: str
    icon: str
    probe_url: str
    auth_header: Callable[[str], dict[str, str]]
    sync_url: str | None = None  # if None, sync just re-probes
    parse_probe: Callable[[Any], dict[str, Any]] | None = None
    parse_sync: Callable[[Any], dict[str, Any]] | None = None
    scopes: list[str] = field(default_factory=list)
    per_user: bool = False  # True = personal_apikey, False = project_apikey


def make_provider(spec: ProviderSpec) -> type[IntegrationProvider]:
    class _ApiKeyProvider(IntegrationProvider):
        slug = spec.slug
        kind = "personal_apikey" if spec.per_user else "project_apikey"
        display_name = spec.display_name
        category = spec.category
        description = spec.description
        docs_url = spec.docs_url
        icon = spec.icon

        async def _probe(self, api_key: str) -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    spec.probe_url, headers=spec.auth_header(api_key)
                )
            if resp.status_code in (401, 403):
                raise IntegrationError(
                    "invalid_key", f"{spec.display_name} rejected the key."
                )
            resp.raise_for_status()
            body = decode_json(resp, provider_name=spec.display_name)
            # No on_error hook: connect() has not created an Integration row
            # yet at this point, so there is nothing to mark as errored.
            return await guarded_parse(
                spec.parse_probe,
                body,
                provider_name=spec.display_name,
                stage="probe",
                error_code="probe_parse_failed",
                message=lambda exc: (
                    f"Could not read {spec.display_name}'s response: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        async def connect(self, *, user, db, payload):  # type: ignore[override]
            api_key = require_api_key(payload)
            try:
                probe = await self._probe(api_key)
            except httpx.HTTPError as exc:
                raise IntegrationError(
                    "probe_failed",
                    f"Could not reach {spec.display_name}: {type(exc).__name__}",
                ) from exc
            if spec.per_user and user is None:
                raise IntegrationError("auth_required", "User context required.")
            return await store_api_key(
                db=db,
                slug=spec.slug,
                api_key=api_key,
                extra=probe,
                scopes=spec.scopes,
                user_id=(user.id if spec.per_user and user else None),
                kind=self.kind,
            )

        async def sync(self, *, integration, db):  # type: ignore[override]
            started = time.perf_counter()
            creds = await db.scalar(
                select(ApiKeyCredential).where(
                    ApiKeyCredential.integration_id == integration.id
                )
            )
            if creds is None:
                raise IntegrationError(
                    "not_connected", f"{spec.display_name} key not stored."
                )
            api_key = decrypt(creds.encrypted_key)
            url = spec.sync_url or spec.probe_url
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, headers=spec.auth_header(api_key))
                    resp.raise_for_status()
                    body = resp.json()
            except Exception as exc:  # noqa: BLE001
                await mark_error(integration=integration, db=db, err=exc)
                raise IntegrationError(
                    "sync_failed", f"{type(exc).__name__}: {exc}"
                ) from exc

            # Any parse failure — a provider's deliberate rejection (e.g. a
            # revoked Slack token) just as much as an unshaped body — must
            # flip the integration to 'error'; otherwise the row stays
            # 'connected' with a stale last_synced_at while sync is
            # silently broken.
            async def _mark_errored(exc: Exception) -> None:
                await mark_error(integration=integration, db=db, err=exc)

            parsed: dict[str, Any] = await guarded_parse(
                spec.parse_sync,
                body,
                provider_name=spec.display_name,
                stage="sync",
                error_code="sync_parse_failed",
                on_error=_mark_errored,
            )

            # Only merge into config after a successful parse — never
            # persist a partial merge from a half-parsed body.
            integration.config = {**(integration.config or {}), **parsed}
            return await mark_synced(
                integration=integration,
                db=db,
                summary=f"Refreshed {spec.display_name} status.",
                started=started,
            )

        async def status(self, *, integration, db):  # type: ignore[override]
            return await project_status(integration=integration, db=db)

    _ApiKeyProvider.__name__ = f"{spec.slug.title()}Integration"
    return _ApiKeyProvider
