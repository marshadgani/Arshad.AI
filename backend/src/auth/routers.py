"""/api/v1/auth/* — login, callback, me, logout.

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

Binding the state to a cookie set on the *backend's own* domain works
here even though frontend and backend are on different domains (Vercel
+ Render): the login → provider-consent → callback round trip is a
direct top-level browser navigation to the backend on both ends — the
frontend domain is never in that path, it only receives the final
token in the redirect fragment after the callback completes. A
SameSite=Lax cookie is sent on exactly this kind of top-level GET
navigation.

Without this, an attacker could complete the OAuth consent flow for
their own account, then get a victim's browser to load the resulting
`code`+`state` against the callback URL — the old signature-only check
would accept it, log the victim into the attacker's account, and every
note/event/email the victim creates afterward lands in an account the
attacker controls. The mitigation follows the same
Redis-getdel-single-use pattern already used correctly by
integrations/personal/_oauth_base.py (store_oauth_state /
consume_oauth_state) for connecting third-party integrations.

Logout is a stateless 204 — the frontend wipes its localStorage JWT.

Attach flow (FEAT-143): the SAME two callback routes below also serve a
third flow — attaching a provider to an ALREADY-authenticated user (e.g.
clicking "Connect" on GitHub/Google Calendar/Drive/etc. on the
Integrations page). GitHub OAuth Apps allow only one registered callback
URI, so a distinct `/attach/callback` endpoint isn't viable without
re-registering the app; instead, the attach flow's state parameter is
minted with an unmistakable `att.` prefix (auth/attach_state.py) that no
login state can ever produce (`_make_signed_state` nonces never contain a
literal '.' before the timestamp segment). Both callbacks check for that
prefix FIRST and, if present, hand off to
integrations/personal/attach_callback.handle_attach_callback — bypassing
the cookie-nonce check entirely for that branch.

This is a deliberate, narrower CSRF posture than the login flow, not an
oversight: the attach state is unguessable (256-bit), single-use (Redis
GETDEL), and — critically — has the target user_id bound into it at MINT
time, inside an authenticated POST (`/integrations/{slug}/connect`, behind
`get_current_user`). An attacker cannot graft their own authorization code
onto a victim's attach state; the identity that ends up receiving the
provider grant comes from Redis, never from anything the callback request
itself carries. A cookie nonce isn't an option here: the flow begins as a
cross-site XHR POST from the Vercel frontend to the Render backend, which
would require `SameSite=None` on the nonce cookie — blocked by Safari and
Chrome's third-party-cookie policies. This matches the accepted posture of
every Phase-H integration provider (integrations/personal/_oauth_base.py),
which has never carried a cookie nonce either.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.urls import frontend_url
from ..middleware.cache import get_redis
from ..models.database import get_db
from ..models.user import User
from .attach_state import ATTACH_STATE_PREFIX
from .dependencies import get_current_user
from .jwt import encode_jwt
from .providers import OAuthProvider, get_login_provider
from .providers.base import OAuthError
from .service import upsert_user_from_oauth

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_STATE_TTL_SECONDS = 300
_NONCE_COOKIE_NAME = "oauth_login_nonce"


def _login_nonce_key(nonce: str) -> str:
    return f"login_oauth_state:{nonce}"


def _cookie_is_secure() -> bool:
    # https backend (Render prod) -> Secure cookie required by browsers.
    # http backend (local dev) -> Secure would silently drop the cookie.
    return os.getenv("BACKEND_URL", "").startswith("https")


def _secret_key() -> str:
    key = os.getenv("SECRET_KEY", "")
    if not key:
        raise RuntimeError("SECRET_KEY env var is required for OAuth state signing")
    return key


def _provider(name: str) -> OAuthProvider:
    """Resolve a login provider, or 404. The *set* of providers lives in
    `providers/registry.py`; only the 404 envelope is this layer's business."""
    provider = get_login_provider(name)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "unknown_provider",
                    "message": f"OAuth provider '{name}' is not configured.",
                    "details": {},
                }
            },
        )
    return provider


def _envelope(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": {}}},
    )


def _make_signed_state(nonce: str) -> str:
    """Return nonce.timestamp.hmac — a self-verifying OAuth state parameter.

    nonce: token_urlsafe chars [A-Za-z0-9_-], no dots.
    timestamp: decimal integer, no dots.
    hmac: hex digest, no dots.
    Splitting on '.' with maxsplit=2 is therefore unambiguous.
    """
    ts = str(int(time.time()))
    payload = f"{nonce}.{ts}"
    sig = hmac.new(_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{ts}.{sig}"


def _verify_signed_state(signed_state: str) -> bool:
    """Return True only if the signed state is structurally valid, unexpired, and HMAC-correct."""
    try:
        nonce, ts_str, sig = signed_state.split(".", 2)
        ts = int(ts_str)
    except ValueError:
        return False
    age = int(time.time()) - ts
    if (
        age < 0 or age > _STATE_TTL_SECONDS
    ):  # negative age = future-dated state (clock skew attack)
        return False
    payload = f"{nonce}.{ts_str}"
    expected = hmac.new(
        _secret_key().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


async def _start_login(provider_name: str) -> RedirectResponse:
    provider = _provider(provider_name)
    nonce = secrets.token_urlsafe(32)
    signed_state = _make_signed_state(nonce)

    redis = await get_redis()
    await redis.set(_login_nonce_key(nonce), "1", ex=_STATE_TTL_SECONDS)

    response = RedirectResponse(
        provider.authorization_url(signed_state), status_code=302
    )
    response.set_cookie(
        _NONCE_COOKIE_NAME,
        nonce,
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        secure=_cookie_is_secure(),
        samesite="lax",
    )
    return response


async def _delegate_to_attach_flow(
    *,
    provider_name: str,
    code: str | None,
    error: str | None,
    state: str,
    db: AsyncSession,
) -> RedirectResponse:
    """The one place `auth` reaches upward into `integrations`.

    Import is function-local on purpose: `integrations.personal` imports
    `auth.providers`, `auth.attach_state` and `auth.service`, so a
    module-level import here would close an import cycle at boot. The
    alternative — a registration hook that `integrations` populates at
    import time — trades a cycle for a startup-ordering dependency, where
    forgetting to import the integrations package turns the attach flow
    into a silent 400 instead of a loud ImportError. Isolating the reach
    in one named function keeps the exception visible and greppable.
    """
    from ..integrations.personal.attach_callback import handle_attach_callback

    return await handle_attach_callback(
        provider_name=provider_name,
        code=code,
        error=error,
        state=state,
        db=db,
    )


async def _handle_callback(
    provider_name: str,
    code: str | None,
    signed_state: str | None,
    error: str | None,
    cookie_nonce: str | None,
    db: AsyncSession,
) -> RedirectResponse:
    # FEAT-143 attach flow: recognise the att.-prefixed state before doing
    # anything login-specific (cookie check, signature check — a login
    # state can never start with this prefix, see module docstring).
    if signed_state and signed_state.startswith(ATTACH_STATE_PREFIX):
        return await _delegate_to_attach_flow(
            provider_name=provider_name,
            code=code,
            error=error,
            state=signed_state,
            db=db,
        )

    if not signed_state or not _verify_signed_state(signed_state):
        raise _envelope(
            status.HTTP_400_BAD_REQUEST,
            "invalid_state",
            "OAuth state is missing, expired, or does not match.",
        )

    state_nonce = signed_state.split(".", 1)[0]
    if not cookie_nonce or not hmac.compare_digest(cookie_nonce, state_nonce):
        raise _envelope(
            status.HTTP_400_BAD_REQUEST,
            "invalid_state",
            "OAuth state does not match this browser session.",
        )

    redis = await get_redis()
    consumed = await redis.getdel(_login_nonce_key(state_nonce))
    if not consumed:
        raise _envelope(
            status.HTTP_400_BAD_REQUEST,
            "invalid_state",
            "OAuth state was already used or has expired.",
        )

    if not code:
        raise _envelope(
            status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            "OAuth callback is missing the authorization code.",
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
    response = RedirectResponse(
        f"{frontend_url()}/auth/callback#token={token}", status_code=302
    )
    response.delete_cookie(_NONCE_COOKIE_NAME)
    return response


@router.get("/google/login", summary="Start Google OAuth")
async def google_login() -> RedirectResponse:
    return await _start_login("google")


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    oauth_login_nonce: str | None = Cookie(default=None, alias=_NONCE_COOKIE_NAME),
) -> RedirectResponse:
    return await _handle_callback("google", code, state, error, oauth_login_nonce, db)


@router.get("/github/login", summary="Start GitHub OAuth")
async def github_login() -> RedirectResponse:
    return await _start_login("github")


@router.get("/github/callback", summary="GitHub OAuth callback")
async def github_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    oauth_login_nonce: str | None = Cookie(default=None, alias=_NONCE_COOKIE_NAME),
) -> RedirectResponse:
    return await _handle_callback("github", code, state, error, oauth_login_nonce, db)


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
