"""/api/v1/auth/* — login, callback, me, logout.

Layering (FEAT-142 restructure — behaviour unchanged):

    oauth_state/signing.py   the `state` param: HMAC, TTL, clock skew
    oauth_state/store.py     the single-use Redis record (fail-closed)
    oauth_state/cookies.py   cookie names, attributes, value validity
    providers/registry.py    which providers exist
    errors.py                the API error envelope
    THIS MODULE              composes them into the flow, and is the only
                             layer that maps a failure onto an HTTP status

OAuth CSRF / login-CSRF / session-fixation protection (SEC-002 fix,
2026-09-07 — see tasks/pipeline-queue.md FEAT-118 for the finding this
closes):

  1. `_start_login` mints a random nonce, signs it into the `state` param
     sent to the provider (self-verifying: nonce.timestamp.hmac), AND
     stores the same nonce in Redis (single-use, 5-min TTL) AND sets it
     as an HttpOnly/SameSite=Lax cookie on the backend's own domain.
  2. `_handle_callback` requires the browser's cookie nonce to match the
     nonce embedded in the returned `state`, then atomically GETDELs the
     Redis entry so the state can never be replayed. Any mismatch or a
     missing/already-consumed Redis entry is rejected as invalid_state.

Binding the state to a cookie set on the *backend's own* domain only
works if the browser's cookie jar is actually keyed to that domain on
BOTH legs of the round trip. The callback leg always is: the provider
redirects the browser directly to BACKEND_URL, so that leg is a direct
top-level navigation to the backend. The LOGIN leg is only a direct
top-level navigation to the backend if the caller navigates to an
*absolute* backend URL. FEAT-142 fixed a production bug where the
frontend (frontend/src/auth/loginUrl.ts) navigated to a *relative*
`/api/v1/auth/<provider>/login` path: on Vercel that path is served by
Vercel's own domain via a server-side `/api/*` rewrite proxy
(frontend/vercel.json), so the browser never left the frontend origin
for the login leg — the Set-Cookie from `_start_login` landed on the
frontend's origin (e.g. arshad-ai-seven.vercel.app), not the backend's.
When the provider then redirected the browser to the callback on the
backend's origin, no cookie was sent (different registrable domain) and
every login failed with "OAuth state does not match this browser
session." The fix is entirely in the frontend: `loginUrl` now builds an
absolute `${VITE_BACKEND_URL}/api/v1/auth/<provider>/login` URL so
Set-Cookie and Cookie are both scoped to the backend's origin on both
legs, exactly as this docstring always intended.

Without this cookie/state binding, an attacker could complete the
OAuth consent flow for their own account, then get a victim's browser
to load the resulting `code`+`state` against the callback URL — the
old signature-only check would accept it, log the victim into the
attacker's account, and every note/event/email the victim creates
afterward lands in an account the attacker controls. The mitigation
follows the same Redis-getdel-single-use pattern already used
correctly by integrations/personal/_oauth_base.py (store_oauth_state /
consume_oauth_state) for connecting third-party integrations.

Logout is a stateless 204 — the frontend wipes its localStorage JWT.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time  # noqa: F401 — re-exported seam: tests patch routers.time.time

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.cache import get_redis
from ..models.database import get_db
from ..models.user import User
from .dependencies import get_current_user
from .errors import envelope as _envelope
from .jwt import encode_jwt
from .oauth_state import (
    BINDER_BYTES,
    BINDER_COOKIE_NAME,
    NONCE_COOKIE_NAME,
    REDIS_ERRORS,
    STATE_TTL_SECONDS,
    LoginStateUnavailable,
    clear_login_cookie,
    is_valid_binder,
    login_nonce_key,
    make_signed_state,
    mint_binder,
    put_state,
    set_login_cookie,
    state_age_seconds,
    state_nonce,
    take_state,
    verify_signed_state,
)
from .providers.base import OAuthError, OAuthProvider
from .providers.registry import build_provider
from .service import upsert_user_from_oauth

# Compatibility surface: these primitives now live in `oauth_state`, but the
# auth test-suite (and any caller predating the split) still addresses them on
# this module. Explicit assignments rather than `import ... as _x` aliases, so
# an autoformatter cannot prune them as unused imports.
_BINDER_BYTES = BINDER_BYTES
_BINDER_COOKIE_NAME = BINDER_COOKIE_NAME
_NONCE_COOKIE_NAME = NONCE_COOKIE_NAME
_REDIS_ERRORS = REDIS_ERRORS
_STATE_TTL_SECONDS = STATE_TTL_SECONDS
_is_valid_binder = is_valid_binder
_login_nonce_key = login_nonce_key
_make_signed_state = make_signed_state
_verify_signed_state = verify_signed_state

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_log = logging.getLogger(__name__)

# W2 (binder redesign) is designed but deliberately not wired up — the
# confirmed production root cause (relative login navigation crossing an
# origin boundary) means the cookie is ABSENT, not stale, so a per-browser
# binder cookie fixes nothing. It is kept behind this flag in case W1's
# post-deploy log evidence (reason=cookie_mismatch, not cookie_absent)
# ever proves otherwise. See tasks/agent-outputs/system-engineer/FEAT-142.json.
OAUTH_STATE_BINDER_ENABLED = (
    os.getenv("OAUTH_STATE_BINDER_ENABLED", "false").lower() == "true"
)

_STATE_REJECTED_LOG = (
    "oauth_login_state_rejected provider=%s reason=%s cookie_present=%s "
    "state_age_seconds=%s user_agent=%r callback_host=%s"
)


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def _provider(name: str) -> OAuthProvider:
    provider = build_provider(name)
    if provider is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "unknown_provider",
            f"OAuth provider '{name}' is not configured.",
        )
    return provider


class _CallbackContext:
    """The diagnostic fields every rejection log line carries.

    Bundled so `_reject_state` has one short signature and no call site
    can omit a field and quietly produce a log line that can't be
    correlated with the others.
    """

    __slots__ = ("provider", "cookie_present", "state_age", "user_agent", "host")

    def __init__(
        self,
        provider: str,
        cookie_present: bool,
        state_age: int | None,
        user_agent: str,
        host: str,
    ) -> None:
        self.provider = provider
        self.cookie_present = cookie_present
        self.state_age = state_age
        self.user_agent = user_agent
        self.host = host


def _reject_state(ctx: _CallbackContext, reason: str, message: str) -> HTTPException:
    """Log why a login state was rejected, return the client-facing 400.

    `reason` discriminates the failure mode in the log ONLY. Every
    rejection returns a byte-identical body for a given message, so the
    response can never become an oracle telling an attacker whether
    their cookie was absent or merely wrong (test T7).
    """
    _log.warning(
        _STATE_REJECTED_LOG,
        ctx.provider,
        reason,
        ctx.cookie_present,
        ctx.state_age,
        ctx.user_agent[:120],
        ctx.host,
    )
    return _envelope(status.HTTP_400_BAD_REQUEST, "invalid_state", message)


def _login_unavailable(phase: str, exc: BaseException) -> HTTPException:
    """Single fail-closed exit for every Redis outage in the login flow."""
    _log.error("oauth_redis_unavailable phase=%s error=%s", phase, type(exc).__name__)
    return _envelope(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "login_unavailable",
        "Login is temporarily unavailable. Please try again.",
    )


async def _redis_or_503():
    try:
        return await get_redis()
    except REDIS_ERRORS as exc:
        raise _login_unavailable("connect", exc)


async def _start_login(
    provider_name: str, existing_binder: str | None = None
) -> RedirectResponse:
    provider = _provider(provider_name)
    nonce = secrets.token_urlsafe(32)
    signed_state = make_signed_state(nonce)
    redis = await _redis_or_503()

    if OAUTH_STATE_BINDER_ENABLED:
        cookie_name = BINDER_COOKIE_NAME
        cookie_value = mint_binder(existing_binder)
        stored_value = hashlib.sha256(cookie_value.encode()).hexdigest()
    else:
        cookie_name = NONCE_COOKIE_NAME
        cookie_value = nonce
        stored_value = "1"

    try:
        await put_state(redis, nonce, stored_value, ttl=STATE_TTL_SECONDS)
    except LoginStateUnavailable as exc:
        raise _login_unavailable(exc.phase, exc.cause)

    response = RedirectResponse(
        provider.authorization_url(signed_state), status_code=302
    )
    response.headers["Cache-Control"] = "no-store"
    set_login_cookie(response, cookie_name, cookie_value, max_age=STATE_TTL_SECONDS)
    return response


async def _handle_callback(
    provider_name: str,
    code: str,
    signed_state: str,
    cookie_nonce: str | None,
    db: AsyncSession,
    *,
    user_agent: str = "",
    callback_host: str = "",
) -> RedirectResponse:
    ctx = _CallbackContext(
        provider=provider_name,
        cookie_present=bool(cookie_nonce),
        state_age=state_age_seconds(signed_state),
        user_agent=user_agent,
        host=callback_host,
    )

    if not verify_signed_state(signed_state):
        raise _reject_state(
            ctx,
            "bad_signature",
            "OAuth state is missing, expired, or does not match.",
        )

    nonce = state_nonce(signed_state)

    if not OAUTH_STATE_BINDER_ENABLED:
        # Flag-off (shipping) path: the cookie IS the per-attempt nonce
        # itself, so it can be checked before touching Redis at all.
        if not cookie_nonce or not hmac.compare_digest(cookie_nonce, nonce):
            raise _reject_state(
                ctx,
                "cookie_absent" if not cookie_nonce else "cookie_mismatch",
                "OAuth state does not match this browser session.",
            )

    redis = await _redis_or_503()
    try:
        consumed = await take_state(redis, nonce)
    except LoginStateUnavailable as exc:
        raise _login_unavailable(exc.phase, exc.cause)

    if not consumed:
        raise _reject_state(
            ctx,
            "redis_consumed_or_expired",
            "OAuth state was already used or has expired.",
        )

    if OAUTH_STATE_BINDER_ENABLED:
        # Redis now holds sha256(binder) as a commitment; the browser's binder
        # cookie must hash to exactly that value. Consumed regardless of
        # outcome above (GETDEL already ran) so a rejected callback can't retry.
        if not cookie_nonce:
            raise _reject_state(
                ctx,
                "cookie_absent",
                "OAuth state does not match this browser session.",
            )
        if not hmac.compare_digest(
            hashlib.sha256(cookie_nonce.encode()).hexdigest(), consumed
        ):
            raise _reject_state(
                ctx,
                "cookie_mismatch",
                "OAuth state does not match this browser session.",
            )

    provider = _provider(provider_name)
    try:
        bundle = await provider.exchange_code(code)
        info = await provider.fetch_user_info(bundle.access_token)
    except OAuthError as exc:
        raise _envelope(status.HTTP_400_BAD_REQUEST, exc.code, exc.message)
    except httpx.HTTPStatusError as exc:
        raise _envelope(
            status.HTTP_502_BAD_GATEWAY,
            "oauth_provider_http_error",
            f"{provider_name} returned {exc.response.status_code} during OAuth.",
        )
    except httpx.RequestError as exc:
        raise _envelope(
            status.HTTP_502_BAD_GATEWAY,
            "oauth_provider_unreachable",
            f"Could not reach {provider_name}: {type(exc).__name__}.",
        )

    user = await upsert_user_from_oauth(
        db, provider=provider_name, info=info, bundle=bundle
    )
    token = encode_jwt(user.id)
    _log.info("oauth_login_succeeded provider=%s", provider_name)
    response = RedirectResponse(
        f"{_frontend_url()}/auth/callback#token={token}", status_code=302
    )
    response.headers["Cache-Control"] = "no-store"
    # W2 (binder) intentionally does NOT clear the binder cookie on success —
    # it is shared across concurrent tabs/attempts and expires via max_age.
    if not OAUTH_STATE_BINDER_ENABLED:
        clear_login_cookie(response, NONCE_COOKIE_NAME)
    return response


def _callback_cookie(nonce_cookie: str | None, binder_cookie: str | None) -> str | None:
    """Which cookie the callback validates against, per the W2 flag."""
    return binder_cookie if OAUTH_STATE_BINDER_ENABLED else nonce_cookie


@router.get("/google/login", summary="Start Google OAuth")
async def google_login(
    oauth_browser_binder: str | None = Cookie(default=None, alias=BINDER_COOKIE_NAME),
) -> RedirectResponse:
    return await _start_login("google", oauth_browser_binder)


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
    oauth_login_nonce: str | None = Cookie(default=None, alias=NONCE_COOKIE_NAME),
    oauth_browser_binder: str | None = Cookie(default=None, alias=BINDER_COOKIE_NAME),
) -> RedirectResponse:
    return await _handle_callback(
        "google",
        code,
        state,
        _callback_cookie(oauth_login_nonce, oauth_browser_binder),
        db,
        user_agent=request.headers.get("user-agent", ""),
        callback_host=request.url.hostname or "",
    )


@router.get("/github/login", summary="Start GitHub OAuth")
async def github_login(
    oauth_browser_binder: str | None = Cookie(default=None, alias=BINDER_COOKIE_NAME),
) -> RedirectResponse:
    return await _start_login("github", oauth_browser_binder)


@router.get("/github/callback", summary="GitHub OAuth callback")
async def github_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
    oauth_login_nonce: str | None = Cookie(default=None, alias=NONCE_COOKIE_NAME),
    oauth_browser_binder: str | None = Cookie(default=None, alias=BINDER_COOKIE_NAME),
) -> RedirectResponse:
    return await _handle_callback(
        "github",
        code,
        state,
        _callback_cookie(oauth_login_nonce, oauth_browser_binder),
        db,
        user_agent=request.headers.get("user-agent", ""),
        callback_host=request.url.hostname or "",
    )


@router.get("/me", summary="Current authenticated user")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "data": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "avatarUrl": user.avatar_url,
        }
    }


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (no-op server-side)",
)
async def logout():
    pass
