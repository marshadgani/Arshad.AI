"""/api/v1/auth/* — login, callback, me, logout.

OAuth CSRF protection uses a self-verifying signed state parameter:
  "{nonce}.{timestamp}.{hmac_sha256}"
The nonce is random (token_urlsafe), the timestamp enforces a 5-min TTL,
and the HMAC (keyed with SECRET_KEY) proves the state was issued by this
backend. Google echoes the state back unchanged, and the callback verifies
the signature — no cookies, no Redis, no cross-domain issues.

This works correctly regardless of whether the frontend and backend are on
different domains (Vercel + Render), because no browser-stored state is
involved. The signed state in the URL is the entire CSRF token.

Logout is a stateless 204 — the frontend wipes its localStorage JWT.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    if int(time.time()) - ts > _STATE_TTL_SECONDS:
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
    return RedirectResponse(provider.authorization_url(signed_state), status_code=302)


async def _handle_callback(
    provider_name: str,
    code: str,
    signed_state: str,
    db: AsyncSession,
) -> RedirectResponse:
    if not _verify_signed_state(signed_state):
        raise _envelope(
            status.HTTP_400_BAD_REQUEST,
            "invalid_state",
            "OAuth state is missing, expired, or does not match.",
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
    return RedirectResponse(
        f"{_frontend_url()}/auth/callback#token={token}", status_code=302
    )


@router.get("/google/login", summary="Start Google OAuth")
async def google_login() -> RedirectResponse:
    return await _start_login("google")


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _handle_callback("google", code, state, db)


@router.get("/github/login", summary="Start GitHub OAuth")
async def github_login() -> RedirectResponse:
    return await _start_login("github")


@router.get("/github/callback", summary="GitHub OAuth callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _handle_callback("github", code, state, db)


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
