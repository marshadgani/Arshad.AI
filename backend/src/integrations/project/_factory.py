"""Turns a declarative ProviderSpec into a live IntegrationProvider.

The error boundary is the point of this module: every failure leaves
connect()/sync() as an IntegrationError, never as an unhandled exception
the router would surface as a 500. Persistence is delegated wholesale to
`_shared.py` (store_api_key / mark_synced / mark_error / project_status).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import httpx

from ..base import (
    IntegrationError,
    IntegrationProvider,
    UpstreamRevocation,
    safe_detail,
)
from ._shared import (
    load_api_key,
    mark_error,
    mark_synced,
    project_status,
    require_api_key,
    store_api_key,
)

_PROBE_TIMEOUT_S = 10.0
_SYNC_TIMEOUT_S = 15.0

# A parser maps a decoded third-party response body to the dict merged
# into `integration.config`. It may raise IntegrationError to reject the
# body with a domain-specific code; any other exception it raises is
# translated by `_run_parser`.
ResponseParser = Callable[[Any], dict[str, Any]]

# The two call sites a parser can run under. Named so the generated error
# code ("probe_failed" / "sync_failed") can't be a free-form string typo'd
# into a code the frontend has never heard of.
ParserStage = Literal["probe", "sync"]


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
    parse_probe: ResponseParser | None = None
    parse_sync: ResponseParser | None = None
    scopes: list[str] = field(default_factory=list)
    per_user: bool = False  # True = personal_apikey, False = project_apikey
    # What disconnect() does with the third party. Required — see
    # IntegrationProvider.upstream_revocation. It has no default here
    # precisely because a default is what let every provider inherit
    # "revokes nothing" while the UI claimed otherwise; a new spec must
    # answer the question.
    upstream_revocation: UpstreamRevocation = field(kw_only=True)
    # Optional: a coroutine `(api_key: str) -> None` that tells the
    # provider to invalidate this key. Specs that supply one must also
    # declare `revokes_via(...)`; those that don't, `cannot_revoke(...)`.
    # Errors propagate to disconnect(), which logs them and deletes the
    # local copy regardless.
    revoke_key: Callable[[str], Any] | None = None


def _run_parser(
    parser: ResponseParser | None,
    body: Any,
    *,
    display_name: str,
    stage: ParserStage,
) -> dict[str, Any]:
    """Sole invocation path for a spec's parse_probe/parse_sync.

    Guarantees only IntegrationError can escape a parser: anything else a
    parser author might raise (AttributeError, KeyError, ...) becomes a
    clean IntegrationError instead of an unhandled 500. The IntegrationError
    arm must come first, so a parser's own code (e.g. Slack's 'invalid_key')
    is never rewritten into a generic '{stage}_failed'.

    The translated message names only the exception *type*, never its text:
    a parser blowing up on an unexpected body must not echo that body (or a
    fragment of a credential inside it) back to the client.
    """
    if parser is None:
        return {"ok": True}
    try:
        return parser(body)
    except IntegrationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(
            f"{stage}_failed",
            f"{display_name} returned an unexpected response: {type(exc).__name__}",
        ) from exc


def make_provider(spec: ProviderSpec) -> type[IntegrationProvider]:
    class _ApiKeyProvider(IntegrationProvider):
        slug = spec.slug
        kind = "personal_apikey" if spec.per_user else "project_apikey"
        display_name = spec.display_name
        category = spec.category
        description = spec.description
        docs_url = spec.docs_url
        icon = spec.icon
        upstream_revocation = spec.upstream_revocation
        # Mirrored onto the class so registry.register() can check that a
        # spec claiming revokes_via(...) actually supplied a way to do it
        # (see _revoke_upstream's `requires_attr` marker below).
        revoke_key = spec.revoke_key

        async def _get(self, url: str, api_key: str, *, timeout: float):
            """The only HTTP call site here. Raises httpx.HTTPError on
            transport failure; callers own the translation, because probe
            and sync report it differently."""
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.get(url, headers=spec.auth_header(api_key))

        async def _probe(self, api_key: str) -> dict[str, Any]:
            resp = await self._get(spec.probe_url, api_key, timeout=_PROBE_TIMEOUT_S)
            if resp.status_code in (401, 403):
                raise IntegrationError(
                    "invalid_key", f"{spec.display_name} rejected the key."
                )
            resp.raise_for_status()
            try:
                body = resp.json()
            except ValueError as exc:
                # connect() only translates IntegrationError/httpx.HTTPError;
                # a non-JSON 2xx body would otherwise escape as a 500.
                raise IntegrationError(
                    "probe_failed",
                    f"{spec.display_name} returned a non-JSON response.",
                ) from exc
            return _run_parser(
                spec.parse_probe, body, display_name=spec.display_name, stage="probe"
            )

        async def _stored_api_key(self, *, integration, db) -> str:
            return await load_api_key(
                integration=integration, db=db, display_name=spec.display_name
            )

        async def _fetch_sync_config(self, api_key: str) -> dict[str, Any]:
            """Refresh payload for sync(). Unlike _probe, a non-JSON body is
            left to sync()'s generic handler — every sync failure lands in
            `last_error` with the same '<Type>: <detail>' shape, and a
            bespoke message here would make that column inconsistent."""
            resp = await self._get(
                spec.sync_url or spec.probe_url, api_key, timeout=_SYNC_TIMEOUT_S
            )
            resp.raise_for_status()
            return _run_parser(
                spec.parse_sync,
                resp.json(),
                display_name=spec.display_name,
                stage="sync",
            )

        async def connect(self, *, user, db, payload):  # type: ignore[override]
            if spec.per_user and user is None:
                raise IntegrationError("auth_required", "User context required.")
            api_key = require_api_key(payload)
            try:
                probe = await self._probe(api_key)
            except httpx.HTTPError as exc:
                raise IntegrationError(
                    "probe_failed",
                    f"Could not reach {spec.display_name}: {type(exc).__name__}",
                ) from exc
            return await store_api_key(
                db=db,
                slug=spec.slug,
                api_key=api_key,
                extra=probe,
                scopes=spec.scopes,
                user_id=(user.id if spec.per_user and user else None),
                kind=("personal_apikey" if spec.per_user else "project_apikey"),
            )

        async def sync(self, *, integration, db):  # type: ignore[override]
            started = time.perf_counter()
            api_key = await self._stored_api_key(integration=integration, db=db)
            try:
                parsed = await self._fetch_sync_config(api_key)
            except IntegrationError as exc:
                # Re-raised verbatim so the parser's own code (e.g. Slack's
                # 'invalid_key') survives; this arm must precede the generic
                # one below or it would be rewritten.
                await mark_error(integration=integration, db=db, err=exc)
                raise
            except Exception as exc:  # noqa: BLE001
                await mark_error(integration=integration, db=db, err=exc)
                raise IntegrationError("sync_failed", safe_detail(exc)) from exc
            integration.config = {**(integration.config or {}), **parsed}
            return await mark_synced(
                integration=integration,
                db=db,
                summary=f"Refreshed {spec.display_name} status.",
                started=started,
            )

        async def status(self, *, integration, db):  # type: ignore[override]
            return await project_status(integration=integration, db=db)

        async def _revoke_upstream(self, *, integration, db):  # type: ignore[override]
            """Invalidate the key at the provider, when the spec knows how.

            Reads the key through the same _stored_api_key() path sync()
            uses, so a rotated OAUTH_ENCRYPTION_KEY surfaces as the usual
            `not_connected` IntegrationError rather than a bare decrypt
            error — and disconnect() logs it and deletes the local rows
            anyway, which is the right outcome either way.
            """
            if spec.revoke_key is None:
                return None
            api_key = await self._stored_api_key(integration=integration, db=db)
            await spec.revoke_key(api_key)

        _revoke_upstream.requires_attr = "revoke_key"  # type: ignore[attr-defined]

    _ApiKeyProvider.__name__ = f"{spec.slug.title()}Integration"
    return _ApiKeyProvider
