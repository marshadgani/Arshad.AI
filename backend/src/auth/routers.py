"""/api/v1/auth/* — login, callback, me, logout.

State is carried in a signed HttpOnly cookie (HMAC-SHA256 over
"state|provider|timestamp" with SECRET_KEY, 5-min TTL). This eliminates
the Redis dependency for OAuth state — Redis is still used elsewhere, but
a Redis outage or cold-start state loss no longer breaks the login flow.

The cookie path is restricted to /api/v1/auth so it is only sent to the
backend, not leaked to the frontend proxy or other routes.

Logout is a stateless 204 — the frontend wipes its localStorage JWT.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import get_db
from ..models.user import User
from .dependencies import get_current_user
from .jwt import encode_jwt
from .providers import GitHubOAuthProvider, GoogleOAuthProvider, OAuthProvider
from .providers.base import OAuthError
from .service import upsert_user_from_oauth

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_STATE_TTL_SECONDS = 300
_COOKIE_NAME = "oauth_state"
_COOKIE_PATH = "/api/v1/auth"


def _secret_key() -> str:
    return os.getenv("SECRET_KEY", "")


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def _is_https() -> bool:
    return os.getenv("BACKEND_URL", "http://localhost:8000").startswith("https://")


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


def _make_state_cookie(state: str, provider: str) -> str:
    ts = str(int(time.time()))
    payload = f"{state}|{provider}|{ts}"
    sig = hmac.new(_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def _verify_state_cookie(cookie: str, url_state: str, provider: str) -> bool:
    try:
        state, prov, ts_str, sig = cookie.split("|", 3)
    except ValueError:
        return False
    if state != url_state or prov != provider:
        return False
    if int(time.time()) - int(ts_str) > _STATE_TTL_SECONDS:
        return False
    payload = f"{state}|{prov}|{ts_str}"
    expected = hmac.new(
        _secret_key().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


async def _start_login(provider_name: str) -> RedirectResponse:
    provider = _provider(provider_name)
    state = secrets.token_urlsafe(32)
    cookie_val = _make_state_cookie(state, provider_name)
    response = RedirectResponse(provider.authorization_url(state), status_code=302)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=cookie_val,
        httponly=True,
        samesite="lax",
        secure=_is_https(),
        max_age=_STATE_TTL_SECONDS,
        path=_COOKIE_PATH,
    )
    return response


async def _handle_callback(
    provider_name: str,
    code: str,
    state: str,
    db: AsyncSession,
    request: Request,
) -> RedirectResponse:
    cookie = request.cookies.get(_COOKIE_NAME, "")
    if not _verify_state_cookie(cookie, state, provider_name):
        raise _envelope(
            status.HTTP_400_BAD_REQUEST,
            "invalid_state",
            "OAuth state is missing, expired, already used, or does not match.",
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
    response.delete_cookie(key=_COOKIE_NAME, path=_COOKIE_PATH)
    return response


@router.get("/google/login", summary="Start Google OAuth")
async def google_login() -> RedirectResponse:
    return await _start_login("google")


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _handle_callback("google", code, state, db, request)


@router.get("/github/login", summary="Start GitHub OAuth")
async def github_login() -> RedirectResponse:
    return await _start_login("github")


@router.get("/github/callback", summary="GitHub OAuth callback")
async def github_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _handle_callback("github", code, state, db, request)


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
