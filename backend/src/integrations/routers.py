"""REST endpoints for the integrations layer.

GET    /api/v1/integrations
       List all known providers + per-(user,slug) status. Returns both
       personal_oauth (filtered by current user) and project_apikey rows.

POST   /api/v1/integrations/{slug}/connect
       OAuth → returns {redirect_url}. API-key → body {api_key}.

POST   /api/v1/integrations/{slug}/sync
       Triggers a sync. Synchronous providers return
       {mode: 'completed', rows_written, summary, duration_ms}. Queue/DAG-
       backed providers (google_calendar, gmail, github) return
       {mode: 'queued', job_id, status: 'pending', summary} instead of a
       fabricated success — actual completion must be polled via
       GET /{slug}/sync/status. See CLAUDE.md FEAT-144.

POST   /api/v1/integrations/{slug}/disconnect
       Clears every stored per-integration credential atomically, then
       marks the integration disconnected. Which tables hold credentials
       and how each is cleared is defined once, in
       services/integration_credentials.py — deliberately not restated
       here, so this docstring cannot go stale against the policy it
       describes. Whether the third party is also told to stop honouring
       the credential is per-provider and declared by each one as
       `upstream_revocation` (base.py) — surfaced on every integration
       card so the disconnect dialog states what will really happen
       rather than one blanket claim. Where revocation is supported, its
       failure is logged and never blocks the local deletion.

GET    /api/v1/integrations/{slug}/status
       Returns the latest connection status snapshot (last_synced_at,
       last_error) — NOT the same thing as sync/status below, which
       tracks one specific enqueued job.

GET    /api/v1/integrations/{slug}/sync/status
       Polls the latest DagTriggerQueue job for this (user, slug). 404 for
       providers with no sync_dag_id (synchronous providers have no job to
       poll — check GET /{slug}/status instead).

This module handles HTTP concerns only — auth dependencies, status codes,
and turning provider outcomes into responses. Two things it deliberately
no longer does itself:

  - response shaping lives in presenters.py, so the list endpoint and the
    per-slug status endpoint cannot describe the same integration two
    different ways;
  - dag_trigger_queue access lives in services/dag_queue.py, so the
    "always scope by user_id" rule behind job polling is enforced in one
    place shared with the Obsidian sync endpoints.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.errors import http_error
from ..auth.dependencies import get_current_user
from ..models.database import get_db
from ..models.integration import Integration
from ..models.user import User
from ..services import dag_queue
from ..services.sync_status import project_job
from . import presenters
from .base import IntegrationError, IntegrationProvider
from .project._shared import preload_api_key_credentials
from .registry import INTEGRATION_REGISTRY, get_provider

_log = logging.getLogger(__name__)


def _frontend_url_env() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


def _require_provider(slug: str) -> IntegrationProvider:
    """Resolve a registered provider or 404.

    Every /{slug}/* route began with this same lookup-or-404; hoisting it
    keeps the "unknown integration" contract defined once.
    """
    provider = get_provider(slug)
    if provider is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "unknown_integration",
            f"No integration '{slug}'.",
        )
    return provider


async def _find_user_integration(
    slug: str, user: User, db: AsyncSession
) -> Integration | None:
    """The integration row for this slug visible to this user.

    user_id IS NULL matches project-scoped (non-personal) integrations,
    which are shared rather than owned by one user.
    """
    return await db.scalar(
        select(Integration).where(
            Integration.slug == slug,
            (Integration.user_id == user.id) | (Integration.user_id.is_(None)),
        )
    )


async def _status_fields_for(
    provider: IntegrationProvider,
    existing: Integration | None,
    db: AsyncSession,
) -> dict[str, Any]:
    """Per-user status half of a card, with the "one broken provider must
    not blank the whole list" guarantee applied once, here, rather than
    as a try/except nested inside the list comprehension's caller."""
    if existing is None:
        return presenters.disconnected_status_fields()
    try:
        report = await provider.status(integration=existing, db=db)
    except Exception:  # noqa: BLE001 — one bad provider must not blank the list
        # The full exception is captured here; per .claude/rules/api.md the
        # client only ever sees the generic message from presenters.
        _log.exception(
            "provider.status() raised for %s during list_integrations",
            provider.slug,
        )
        return presenters.unavailable_status_fields()
    return presenters.status_fields(report)


@router.get("", summary="List integrations + per-user status")
async def list_integrations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(Integration).where(
                (Integration.user_id == user.id) | (Integration.user_id.is_(None))
            )
        )
    ).all()
    by_slug: dict[str, Integration] = {r.slug: r for r in rows}

    # Batch-load every api-key provider's credential row in one query
    # instead of the N sequential SELECTs project_status() would otherwise
    # issue below — one per registered provider (~20+, growing with every
    # bulk_providers.py addition) on every page load of /integrations.
    await preload_api_key_credentials(db, [r.id for r in rows])

    items = [
        {
            **presenters.provider_descriptor(provider),
            **await _status_fields_for(provider, by_slug.get(provider.slug), db),
        }
        for provider in INTEGRATION_REGISTRY.values()
    ]

    items.sort(key=lambda m: (m["category"], m["display_name"]))
    return {"data": items, "total": len(items)}


@router.post("/{slug}/connect", summary="Start a connection")
async def connect_integration(
    slug: str,
    payload: dict[str, Any] | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = _require_provider(slug)
    try:
        result = await provider.connect(user=user, db=db, payload=payload or {})
    except IntegrationError as exc:
        raise http_error(status.HTTP_400_BAD_REQUEST, exc.code, exc.message) from exc
    return {
        "data": presenters.connect_payload(
            integration_id=result.integration_id,
            redirect_url=result.redirect_url,
            ingest_token=result.ingest_token,
        )
    }


@router.post("/{slug}/sync", summary="Trigger sync")
async def sync_integration(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = _require_provider(slug)
    integration = await _find_user_integration(slug, user, db)
    if integration is None:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "not_connected",
            f"Integration '{slug}' is not connected. Connect it first.",
        )
    try:
        result = await provider.sync(integration=integration, db=db)
    except IntegrationError as exc:
        raise http_error(status.HTTP_400_BAD_REQUEST, exc.code, exc.message) from exc

    return {"data": presenters.sync_trigger_payload(result)}


@router.post("/{slug}/disconnect", summary="Disconnect integration")
async def disconnect_integration(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = _require_provider(slug)
    integration = await _find_user_integration(slug, user, db)
    if integration is None:
        return {"data": {"status": "already_disconnected"}}
    await provider.disconnect(integration=integration, db=db)
    return {"data": {"status": "disconnected"}}


@router.get("/{slug}/status", summary="Get latest status")
async def integration_status(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = _require_provider(slug)
    integration = await _find_user_integration(slug, user, db)
    if integration is None:
        return {"data": presenters.disconnected_status_payload(slug)}
    report = await provider.status(integration=integration, db=db)
    return {"data": presenters.status_payload(slug, report)}


def _parse_job_id(job_id: str | None) -> uuid.UUID | None:
    """Validate the optional ?job_id filter at the HTTP boundary.

    The scoping guarantee it feeds into (job_id is only ever AND'd onto
    user_id, never a substitute for it) is enforced by dag_queue.latest_job.
    """
    if not job_id:
        return None
    try:
        return uuid.UUID(job_id)
    except ValueError:
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_job_id",
            "job_id must be a UUID.",
        ) from None


@router.get("/{slug}/sync/status", summary="Poll the latest enqueued sync job")
async def sync_job_status(
    slug: str,
    job_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = _require_provider(slug)
    if provider.sync_dag_id is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "unknown_sync_job",
            f"'{slug}' syncs synchronously — there is no job to poll.",
        )

    row = await dag_queue.latest_job(
        db,
        user_id=user.id,
        dag_id=provider.sync_dag_id,
        job_id=_parse_job_id(job_id),
    )
    if row is None:
        return {"data": None}
    return {"data": project_job(row)}


# ── Generic OAuth callback (Phase H) ─────────────────────────────────────


@router.get("/oauth/{slug}/callback", summary="OAuth provider callback")
async def oauth_callback(
    slug: str,
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Generic OAuth callback for Phase H integration providers.

    No auth dependency — Google/Spotify/etc. don't carry the user's JWT
    on the redirect. Identity comes from the state token (created by
    /connect, stored in Redis with user_id). The handler:

      1. Atomically getdel state from Redis → recovers (user_id, slug)
      2. Cross-checks the slug matches the URL param
      3. Calls provider.exchange_code(code) → token bundle
      4. Calls provider.fetch_profile(access_token) → identity
      5. Upserts integration + integration_oauth_tokens
      6. Redirects browser back to /integrations?connected=<slug>

    All redirect destinations are on FRONTEND_URL.
    """
    from ._oauth_base import (
        OAuthCallbackContext,
        OAuthIntegrationProvider,
        consume_oauth_state,
        upsert_oauth_integration,
    )

    frontend = _frontend_url_env()

    if error:
        return RedirectResponse(
            f"{frontend}/integrations?error={error}&slug={slug}", status_code=302
        )
    if not code or not state:
        return RedirectResponse(
            f"{frontend}/integrations?error=missing_code_or_state&slug={slug}",
            status_code=302,
        )

    triple = await consume_oauth_state(state)
    if triple is None:
        return RedirectResponse(
            f"{frontend}/integrations?error=invalid_state&slug={slug}",
            status_code=302,
        )
    user_id, recorded_slug, stored_ctx = triple
    if recorded_slug != slug:
        return RedirectResponse(
            f"{frontend}/integrations?error=slug_mismatch&slug={slug}",
            status_code=302,
        )

    provider = get_provider(slug)
    if not isinstance(provider, OAuthIntegrationProvider):
        return RedirectResponse(
            f"{frontend}/integrations?error=not_oauth_provider&slug={slug}",
            status_code=302,
        )

    try:
        callback_ctx = OAuthCallbackContext(
            code=code,
            state=state,
            user_id=user_id,
            query_params=dict(request.query_params),
            stored=stored_ctx,
        )
        outcome = await provider.complete_callback(context=callback_ctx)
        await upsert_oauth_integration(
            user_id=user_id,
            slug=slug,
            db=db,
            token_response=outcome.token_response,
            profile=outcome.profile,
            scopes=list(provider.scopes),
            config_extra=outcome.config_extra,
        )
    except IntegrationError as exc:
        _log.exception("OAuth callback for %s failed", slug)
        return RedirectResponse(
            f"{frontend}/integrations?error={exc.code}&slug={slug}", status_code=302
        )
    except Exception:  # noqa: BLE001
        _log.exception("OAuth callback for %s crashed", slug)
        return RedirectResponse(
            f"{frontend}/integrations?error=callback_crashed&slug={slug}",
            status_code=302,
        )

    return RedirectResponse(
        f"{frontend}/integrations?connected={slug}", status_code=302
    )
