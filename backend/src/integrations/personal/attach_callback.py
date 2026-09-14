"""Finishing half of the "attach provider to current user" OAuth callback.

Invoked from auth/routers.py the moment a Google/GitHub callback's `state`
carries the `att.` prefix (auth/attach_state.ATTACH_STATE_PREFIX) — see that
router's module docstring for why this lives on the SAME registered
callback URL as login rather than a new endpoint.

Every outcome here is a 302 redirect to the Integrations page — never an
unhandled exception, never a raw JSON/HTML error page in the browser. That
guarantee is the entire point of this feature: the old behaviour silently
bounced an authenticated user back to '/', discarding the reason. This
module makes every failure mode land back on /integrations with an
explicit, human-readable `?error=<code>`.

The guarantee used to be spelled out as six near-identical `except`
blocks, each logging and building the same redirect by hand. It is now
one declarative table (`_ERROR_CODE_BY_EXC`) plus one `except Exception`
backstop, so "did we remember to redirect on this failure?" is answerable
by reading a five-entry mapping instead of auditing a hundred-line try.
"""

from __future__ import annotations

import logging
from typing import Final
from urllib.parse import urlencode

import httpx
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.attach_state import AttachError, consume_attach_state
from ...auth.providers import get_login_provider
from ...auth.providers.base import OAuthError
from ...auth.service import attach_oauth_account_to_user
from ...config.urls import frontend_url
from ...models.user import User
from ..base import IntegrationError
from ._shared import finalize_attached_integration

_log = logging.getLogger(__name__)

# Exception type -> (?error= code shown on the Integrations page, log with
# traceback?). An empty code means "the exception carries its own `.code`".
# Transport failures are logged with a traceback because the useful detail
# is in the stack; domain rejections are one-liners whose `.code` says it all.
_ERROR_CODE_BY_EXC: Final[tuple[tuple[type[BaseException], str, bool], ...]] = (
    (AttachError, "", False),
    (IntegrationError, "", False),
    (OAuthError, "", False),
    (httpx.HTTPStatusError, "oauth_provider_http_error", True),
    (httpx.RequestError, "oauth_provider_unreachable", True),
)


class _AttachFlowFailed(Exception):
    """Internal: a step failed and already knows its redirect code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _integrations_url(**params: str) -> str:
    base = f"{frontend_url()}/integrations"
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{base}?{query}" if query else base


def _success_redirect(slug: str) -> RedirectResponse:
    return RedirectResponse(_integrations_url(connected=slug), status_code=302)


def _error_redirect(code: str, slug: str = "") -> RedirectResponse:
    return RedirectResponse(_integrations_url(error=code, slug=slug), status_code=302)


def _redirect_plan_for(exc: BaseException) -> tuple[str, bool] | None:
    """(?error= code, log-with-traceback) for `exc`, or None if unanticipated."""
    for exc_type, fallback, with_traceback in _ERROR_CODE_BY_EXC:
        if isinstance(exc, exc_type):
            code = fallback or getattr(exc, "code", "") or "attach_failed"
            return code, with_traceback
    return None


async def _complete_attach(
    *,
    provider_name: str,
    code: str,
    user_id: str,
    slug: str,
    db: AsyncSession,
) -> int:
    """Exchange the code, attach the identity, promote to an Integration.

    Returns the number of scopes actually granted (for the success log).
    Raises `_AttachFlowFailed` for every anticipated failure.
    """
    provider = get_login_provider(provider_name)
    if provider is None:
        raise _AttachFlowFailed("unknown_provider")

    bundle = await provider.exchange_code(code)
    info = await provider.fetch_user_info(bundle.access_token)

    account = await attach_oauth_account_to_user(
        db, user_id=user_id, provider=provider_name, info=info, bundle=bundle
    )

    user = await db.scalar(select(User).where(User.id == account.user_id))
    if user is None:
        _log.warning("attach flow: user %s missing after attach", user_id)
        raise _AttachFlowFailed("user_missing")

    await finalize_attached_integration(
        user=user, db=db, slug=slug, oauth_provider=provider_name
    )
    return len(bundle.scopes or [])


async def handle_attach_callback(
    *,
    provider_name: str,
    code: str | None,
    error: str | None,
    state: str,
    db: AsyncSession,
) -> RedirectResponse:
    payload = await consume_attach_state(state)
    if payload is None:
        return _error_redirect("invalid_state")

    slug = payload.return_slug

    if payload.provider != provider_name:
        _log.warning(
            "attach state provider mismatch: stored=%s callback=%s slug=%s",
            payload.provider,
            provider_name,
            slug,
        )
        return _error_redirect("provider_mismatch", slug)

    if error is not None or not code:
        _log.info(
            "attach flow cancelled: provider=%s slug=%s error=%s",
            provider_name,
            slug,
            error or "no_code",
        )
        return _error_redirect("access_denied", slug)

    try:
        scope_count = await _complete_attach(
            provider_name=provider_name,
            code=code,
            user_id=payload.user_id,
            slug=slug,
            db=db,
        )
    except _AttachFlowFailed as exc:
        return _error_redirect(exc.code, slug)
    except Exception as exc:  # noqa: BLE001 — must still redirect, never 500
        plan = _redirect_plan_for(exc)
        if plan is None:
            _log.exception(
                "attach flow crashed: provider=%s slug=%s", provider_name, slug
            )
            return _error_redirect("callback_crashed", slug)
        redirect_code, with_traceback = plan
        log = _log.exception if with_traceback else _log.warning
        log(
            "attach flow failed: code=%s provider=%s slug=%s exc=%s",
            redirect_code,
            provider_name,
            slug,
            type(exc).__name__,
        )
        return _error_redirect(redirect_code, slug)

    _log.info(
        "attach flow succeeded: provider=%s slug=%s user_id=%s scope_count=%d",
        provider_name,
        slug,
        payload.user_id,
        scope_count,
    )
    return _success_redirect(slug)
