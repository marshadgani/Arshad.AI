"""Wire shapes for the integrations API.

routers.py previously did three jobs at once: HTTP concerns (auth
dependencies, status codes, 404s), orchestration (resolve provider, call
it), and presentation (hand-building every response dict inline, twice
for status). The presentation half lives here so that:

  - the shape of an integration card is defined in one place, whether it
    comes from the list endpoint or the per-slug status endpoint;
  - the SyncResult | EnqueuedResult discriminator — the whole point of
    FEAT-144's "don't fabricate a success" fix — is applied by one
    function rather than by an isinstance branch inside a route handler;
  - a route handler reads as a sequence of decisions, not as a dict
    literal with logic threaded through it.

Nothing here touches the database or raises HTTP errors; these are pure
functions over already-resolved domain objects.
"""

from __future__ import annotations

from typing import Any

from .base import (
    EnqueuedResult,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)

# Shown instead of an exception's text when a provider's status() blows
# up. Per .claude/rules/api.md, internal exception details (stack traces,
# provider internals) must never reach the client; the caller logs the
# real exception.
STATUS_FETCH_FAILED_MESSAGE = "Failed to fetch status for this integration."


def provider_descriptor(p: IntegrationProvider) -> dict[str, Any]:
    """The static, user-independent half of an integration card."""
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
        # What disconnect() will actually do with the third party, so the
        # confirmation dialog can say it per provider. Without this the
        # frontend has no basis for the claim and has to pick one blanket
        # sentence for all 44 — which is how it came to promise
        # "credentials revoked with the provider" for providers that
        # revoke nothing.
        "upstream_revocation": {
            "supported": p.upstream_revocation.supported,
            "detail": p.upstream_revocation.detail,
        },
    }


def status_fields(report: StatusReport) -> dict[str, Any]:
    """The dynamic, per-user half of an integration card."""
    return {
        "status": report.status,
        "last_synced_at": report.last_synced_at,
        "last_error": report.last_error,
        "extra": report.extra,
    }


def disconnected_status_fields() -> dict[str, Any]:
    """For a provider the user has no Integration row for at all."""
    return {
        "status": "disconnected",
        "last_synced_at": None,
        "last_error": None,
        "extra": {},
    }


def unavailable_status_fields() -> dict[str, Any]:
    """For a provider whose status() raised — one bad provider must not
    blank the whole list.

    last_synced_at is explicitly null here. The inline version of this
    branch simply never wrote the key, so the error case was the one
    shape in the API where an integration card came back without it;
    every consumer already treats it as nullable (the frontend types it
    `string | null` and only reads it when status === 'connected'), so
    filling it in costs nothing and removes a shape that only existed by
    accident.
    """
    return {
        "status": "error",
        "last_synced_at": None,
        "last_error": STATUS_FETCH_FAILED_MESSAGE,
        "extra": {},
    }


def status_payload(slug: str, report: StatusReport) -> dict[str, Any]:
    return {"slug": slug, **status_fields(report)}


def disconnected_status_payload(slug: str) -> dict[str, Any]:
    return {"slug": slug, **disconnected_status_fields()}


def connect_payload(
    *, integration_id: str | None, redirect_url: str | None, ingest_token: str | None
) -> dict[str, Any]:
    return {
        "integration_id": integration_id,
        "redirect_url": redirect_url,
        "ingest_token": ingest_token,
    }


def sync_trigger_payload(result: SyncResult | EnqueuedResult) -> dict[str, Any]:
    """The honest response to POST /{slug}/sync.

    'queued' carries no rows_written on purpose — nothing has been
    processed yet, only enqueued, and the caller must poll
    GET /{slug}/sync/status for the real outcome. 'completed' is only
    ever emitted by providers that genuinely finished the work inline.
    """
    if isinstance(result, EnqueuedResult):
        return {
            "mode": "queued",
            "job_id": result.job_id,
            "status": "pending",
            "summary": result.summary,
        }
    return {
        "mode": "completed",
        "rows_written": result.rows_written,
        "summary": result.summary,
        "duration_ms": result.duration_ms,
    }
