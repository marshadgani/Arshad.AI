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

from ..middleware.cache import get_redis
from ..models.database import get_db
from ..models.user import User
from .dependencies import get_current_user
from .jwt import encode_jwt
from .providers import GitHubOAuthProvider, GoogleOAuthProvider, OAuthProvider
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


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def _provider(name: str) -> OAuthProvider:
    if name == "google":
        return GoogleOAuthProvider()
    if name == "github":
        return GitHubOAuthProvider()
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

    response = RedirectResponse(provider.authorization_url(signed_state), status_code=302)
    response.set_cookie(
        _NONCE_COOKIE_NAME,
        nonce,
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        secure=_cookie_is_secure(),
        samesite="lax",
    )
    return response


async def _handle_callback(
    provider_name: str,
    code: str,
    signed_state: str,
    cookie_nonce: str | None,
    db: AsyncSession,
) -> RedirectResponse:
    if not _verify_signed_state(signed_state):
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
        f"{_frontend_url()}/auth/callback#token={token}", status_code=302
    )
    response.delete_cookie(_NONCE_COOKIE_NAME)
    return response


@router.get("/google/login", summary="Start Google OAuth")
async def google_login() -> RedirectResponse:
    return await _start_login("google")


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
    oauth_login_nonce: str | None = Cookie(default=None, alias=_NONCE_COOKIE_NAME),
) -> RedirectResponse:
    return await _handle_callback("google", code, state, oauth_login_nonce, db)


@router.get("/github/login", summary="Start GitHub OAuth")
async def github_login() -> RedirectResponse:
    return await _start_login("github")


@router.get("/github/callback", summary="GitHub OAuth callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
    oauth_login_nonce: str | None = Cookie(default=None, alias=_NONCE_COOKIE_NAME),
) -> RedirectResponse:
    return await _handle_callback("github", code, state, oauth_login_nonce, db)


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
