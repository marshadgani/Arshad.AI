"""REST endpoints for the integrations layer.

GET    /api/v1/integrations
       List all known providers + per-(user,slug) status. Returns both
       personal_oauth (filtered by current user) and project_apikey rows.

POST   /api/v1/integrations/{slug}/connect
       OAuth → returns {redirect_url}. API-key → body {api_key}.

POST   /api/v1/integrations/{slug}/sync
       Triggers a sync. Returns {rows_written, summary, duration_ms}.

POST   /api/v1/integrations/{slug}/disconnect
       Revokes the upstream credential where the provider supports it;
       deletes local credential rows for every provider; marks the
       integration disconnected (FEAT-145).

GET    /api/v1/integrations/{slug}/status
       Returns the latest status snapshot.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import (
    RedirectResponse,  # noqa: F401 — used by oauth_callback below
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.errors import http_error
from ..auth.dependencies import get_current_user
from ..config.urls import frontend_url
from ..models.database import get_db
from ..models.integration import Integration
from ..models.user import User
from ..services.ingestion import sync_jobs
from .authz import project_disconnect_decision
from .base import IntegrationError, IntegrationProvider
from .registry import INTEGRATION_REGISTRY, get_provider

_log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


def _provider_descriptor(p: IntegrationProvider) -> dict[str, Any]:
    return {
        "slug": p.slug,
        "kind": p.kind,
        "display_name": p.display_name,
        "category": p.category,
        "description": p.description,
        "docs_url": p.docs_url,
        "icon": p.icon,
        "coming_soon": p.coming_soon,
        "coming_soon_reason": p.coming_soon_reason,
        "connect_prompt": p.connect_prompt,
        # FEAT-145: lets the frontend pick the right pre-disconnect confirm
        # copy ("will be revoked" vs "no revoke API" vs "your sign-in is
        # unaffected") instead of one blanket promise that wasn't true for
        # 24 of 25 providers.
        "revocation_kind": p.revocation_kind,
    }


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


def _parse_job_id(raw: str | None) -> uuid.UUID | None:
    """Validate the optional ?job_id= query param.

    Request-shape validation stays in the HTTP layer; the queue service
    takes a real UUID or nothing. An empty/absent value means "latest job
    for this user+provider", not an error.
    """
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_job_id",
            "job_id must be a UUID.",
        ) from exc


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


async def _find_user_integration_for_disconnect(
    slug: str, user: User, db: AsyncSession
) -> Integration | None:
    """FEAT-145: same lookup as _find_user_integration, plus the admin gate
    on project-scoped rows — the one place the permissive `user_id IS NULL`
    match became dangerous the moment disconnect() started actually
    deleting credential rows (previously it only flipped a status flag, so
    any authenticated user hitting a shared project_apikey integration was
    cosmetic at worst).

    Personal integrations: unchanged, user_id == user.id only. Project
    integrations: the decision belongs to integrations/authz.py; this
    function only translates a 'denied' decision into the HTTP contract.
    """
    integration = await _find_user_integration(slug, user, db)
    if integration is None or integration.user_id is not None:
        return integration

    decision = project_disconnect_decision(slug=slug, user_id=user.id, email=user.email)
    if decision == "denied":
        raise http_error(
            status.HTTP_403_FORBIDDEN,
            "project_integration_admin_required",
            f"Disconnecting '{slug}' requires admin access — it is shared "
            "deployment infrastructure, not a personal credential.",
        )
    return integration


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

    items = []
    for provider in INTEGRATION_REGISTRY.values():
        meta = _provider_descriptor(provider)
        existing = by_slug.get(provider.slug)
        if existing is not None:
            try:
                report = await provider.status(integration=existing, db=db)
                meta["status"] = report.status
                meta["last_synced_at"] = report.last_synced_at
                meta["last_error"] = report.last_error
                meta["extra"] = report.extra
            except Exception:  # noqa: BLE001 — one bad provider must not blank the list
                # Full exception (type, message, traceback) is logged
                # server-side for debugging. The client only ever gets a
                # generic message — provider.status() can raise SQLAlchemy/
                # asyncpg errors that embed connection strings or other
                # internals, and .claude/rules/api.md forbids exposing
                # those to the client.
                _log.exception(
                    "provider.status() raised for %s during list_integrations",
                    provider.slug,
                )
                meta["status"] = "error"
                meta["last_error"] = "Status check failed. See server logs."
                meta["extra"] = {}
        else:
            meta["status"] = "disconnected"
            meta["last_synced_at"] = None
            meta["last_error"] = None
            meta["extra"] = {}
        items.append(meta)

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
        "data": {
            "integration_id": result.integration_id,
            "redirect_url": result.redirect_url,
            "ingest_token": result.ingest_token,
        }
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
    return {
        "data": {
            "rows_written": result.rows_written,
            "summary": result.summary,
            "duration_ms": result.duration_ms,
            # FEAT-144: mode discriminates an honest "queued, not done yet"
            # (DAG-backed providers) from "actually completed" (everything
            # else) — see .claude/rules/api.md's documented-deviation note
            # for why this project prefers an explicit discriminator field
            # over inventing a new HTTP status for "accepted but pending".
            "mode": result.mode,
            "job_id": result.job_id,
        }
    }


@router.get("/{slug}/sync/status", summary="Poll a DAG-backed sync job")
async def sync_job_status(
    slug: str,
    job_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Poll the status of a background sync job enqueued by POST /sync.

    409 (not 401/404-for-capability) for "this provider doesn't work this
    way" mirrors the documented Whoop/Shopify deviation in
    .claude/rules/api.md: the resource's current state (a synchronous
    provider has no job to poll) conflicts with the request, which is what
    409 means.
    """
    provider = _require_provider(slug)
    if provider.sync_dag_id is None:
        raise http_error(
            status.HTTP_409_CONFLICT,
            "sync_not_pollable",
            f"'{slug}' syncs synchronously and has no background job to poll.",
        )

    # sync_jobs owns the user_id+dag_id scoping (another user's job_id is a
    # miss, not a leak); this handler only maps "no such job" onto 404.
    view = await sync_jobs.job_status_view(
        db,
        user_id=user.id,
        dag_id=provider.sync_dag_id,
        job_id=_parse_job_id(job_id),
    )
    if view is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "sync_job_not_found",
            f"No sync job found for '{slug}'.",
        )
    return {"data": view}


@router.post("/{slug}/disconnect", summary="Disconnect integration")
async def disconnect_integration(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = _require_provider(slug)
    integration = await _find_user_integration_for_disconnect(slug, user, db)
    if integration is None:
        return {
            "data": {
                "status": "already_disconnected",
                "upstream_revocation": "unsupported",
            }
        }
    outcome = await provider.disconnect(integration=integration, db=db)
    return {
        "data": {
            "status": outcome.status,
            "upstream_revocation": outcome.upstream_revocation,
        }
    }


@router.get("/{slug}/status", summary="Get latest status")
async def integration_status(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = _require_provider(slug)
    integration = await _find_user_integration(slug, user, db)
    if integration is None:
        return {
            "data": {
                "slug": slug,
                "status": "disconnected",
                "last_synced_at": None,
                "last_error": None,
                "extra": {},
            }
        }
    report = await provider.status(integration=integration, db=db)
    return {
        "data": {
            "slug": slug,
            "status": report.status,
            "last_synced_at": report.last_synced_at,
            "last_error": report.last_error,
            "extra": report.extra,
        }
    }


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

    frontend = frontend_url()

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
