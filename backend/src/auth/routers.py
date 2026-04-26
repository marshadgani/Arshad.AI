"""/api/v1/auth/* — login, callback, me, logout.

State is stored in Redis (``oauth_state:<state> = "<provider>"``, 5-min TTL).
The callback uses ``GETDEL`` to validate-and-consume atomically — a plain
``GET`` then ``DELETE`` would leave a millisecond-wide replay window where
two concurrent callbacks with the same code could both pass validation.

Logout is a stateless 204 — the frontend wipes its localStorage entry.
A real revocation list would require Redis lookups on every authenticated
request, which contradicts our stateless-JWT decision.
"""

from __future__ import annotations

import os
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
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


async def _start_login(provider_name: str) -> RedirectResponse:
    provider = _provider(provider_name)
    state = secrets.token_urlsafe(32)
    redis = await get_redis()
    await redis.set(f"oauth_state:{state}", provider_name, ex=_STATE_TTL_SECONDS)
    return RedirectResponse(provider.authorization_url(state), status_code=302)


async def _handle_callback(
    provider_name: str,
    code: str,
    state: str,
    db: AsyncSession,
) -> RedirectResponse:
    redis = await get_redis()
    stored = await redis.getdel(f"oauth_state:{state}")
    if stored != provider_name:
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
    response_class=Response,
    summary="Logout (no-op server-side)",
)
async def logout() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
