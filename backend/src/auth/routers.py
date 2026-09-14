"""/api/v1/auth/* — OAuth login/callback, password login, me, logout.

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

FEAT-159 adds email/password login as a second, additive credential type
(POST /password/login below) issuing the SAME JWT via the SAME
encode_jwt() the OAuth path already uses. It shares this module for two
reasons: it needs the exact same Redis-outage resilience story as OAuth
(OAuth is the documented login fallback whenever password login is
degraded — either by its fail-CLOSED per-email lockout or by the
PASSWORD_AUTH_ENABLED kill-switch), and putting both paths in one file
keeps that shared story auditable in one place. The two OAuth Redis
calls below (`_start_login`'s `redis.set` and `_handle_callback`'s
`redis.getdel`) are now guarded against RedisError so that claim holds
in practice, not just in a comment.

Logout is a stateless 204 — the frontend wipes its localStorage JWT.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.errors import http_error
from ..middleware.cache import get_redis
from ..middleware.rate_limit import enforce_rate_limit
from ..models.database import get_db
from ..models.user import User
from . import lockout
from .allowlist import is_email_allowed
from .dependencies import get_current_user
from .jwt import encode_jwt
from .password import dummy_verify, verify_password
from .providers import GitHubOAuthProvider, GoogleOAuthProvider, OAuthProvider
from .providers.base import OAuthError
from .service import authenticate_with_password, normalize_email, upsert_user_from_oauth

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_log = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 300
_NONCE_COOKIE_NAME = "oauth_login_nonce"

# Generic body returned on EVERY password-login failure branch (user not
# found, OAuth-only account, wrong password) — identical status, message
# and headers so the response itself carries no user-enumeration signal.
_INVALID_CREDENTIALS_MESSAGE = "Email or password is incorrect."


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
    try:
        await redis.set(_login_nonce_key(nonce), "1", ex=_STATE_TTL_SECONDS)
    except RedisError:
        # Fail open: during an outage OAuth CSRF protection degrades from
        # (HMAC-signed state AND browser cookie AND single-use Redis nonce)
        # to (HMAC-signed state AND browser cookie) — see the matching
        # getdel guard in _handle_callback below for the other half of
        # this trade-off. Both surviving factors are attacker-unforgeable
        # without SECRET_KEY or the user's browser, and the state is
        # TTL-bounded, so this is a time-boxed, outage-only degradation —
        # the price of keeping OAuth genuinely Redis-independent so it can
        # serve as the login fallback while password login's per-email
        # lockout is fail-CLOSED (see auth/lockout.py).
        _log.warning(
            "OAuth login-nonce store skipped — Redis unreachable; "
            "state=%s continuing without single-use replay protection",
            nonce,
        )

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
    redis_down = False
    try:
        consumed = await redis.getdel(_login_nonce_key(state_nonce))
    except RedisError:
        # See the matching comment in _start_login. The single-use replay
        # check is skipped ONLY when Redis itself is unreachable — an
        # absent/already-consumed key with a HEALTHY Redis still 400s
        # below, exactly as before. This distinction is what makes the
        # outage-degradation safe rather than a blanket bypass.
        redis_down = True
        consumed = None
        _log.warning(
            "OAuth single-use nonce check skipped — Redis unreachable; "
            "continuing callback for state=%s",
            state_nonce,
        )
    if not consumed and not redis_down:
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

    if not is_email_allowed(info.email):
        raise _envelope(
            status.HTTP_403_FORBIDDEN,
            "email_not_allowed",
            "This deployment is restricted to its owner's account.",
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


# ── Password login (FEAT-159) ───────────────────────────────────────────────


class PasswordLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


def _password_auth_enabled() -> bool:
    """Read the kill-switch AT REQUEST TIME (never cached, never read at
    import time) so tests can monkeypatch.setenv against an
    already-constructed TestClient/app and so a Render env change takes
    effect on the very next request without a code deploy.

    Defaults ON when unset. Render env vars are set by hand; a default-off
    switch plus a forgotten variable would ship this feature dead behind a
    green pipeline. This default is safe because the endpoint is already
    inert for every account whose password_hash IS NULL — i.e. every
    account, until backend/scripts/set_password.py is deliberately run
    against it.
    """
    raw = os.getenv("PASSWORD_AUTH_ENABLED", "true").strip().lower()
    return raw not in ("false", "0", "no")


@router.post("/password/login", summary="Login with email and password")
async def password_login(
    payload: PasswordLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fixed handler ordering — do not reorder these steps.

    1. Kill-switch first: a disabled feature costs zero Redis and zero DB.
    2. Normalize the email once: every downstream key (lockout bucket,
       DB lookup) derives from this single value, closing the
       whitespace-bypass gap between the limiter and the lookup.
    3. Global backstop (fail-OPEN): bounds worst-case aggregate bcrypt CPU
       across ALL callers, not a per-account guard. It is a single shared
       counter (identity="global") — an unauthenticated caller sending
       requests at the limit can hold it saturated indefinitely, 429-ing
       every other caller's password-login attempts including the real
       owner's. This is a known, accepted tradeoff (Arshad, 2026-09-14,
       see SEC-001): the limit is set high enough that it only engages
       under a genuine flood, not casual retry traffic, and Google/GitHub
       OAuth login is completely unaffected (separate route, separate
       rate-limit bucket) and remains available whenever this bucket is
       saturated — exactly the same fallback story as the per-email
       lockout's fail-closed behaviour below.
    4. Per-email lockout (fail-CLOSED): the actual brute-force guard —
       per-IP limiting was evaluated and found not viable on this
       deployed stack (Vercel external rewrite + a publicly reachable
       Render origin defeat any fixed trusted-hop index), so this bucket
       carries the full defence and must not fail open.
    5. DB lookup — cheap, no bcrypt.
    6. Exactly ONE bcrypt operation, unconditionally, last: dummy_verify
       when there is no real hash to check against (user not found, or
       an OAuth-only account with password_hash IS NULL), verify_password
       otherwise. This ordering — bcrypt last, on every branch — is what
       prevents any earlier branch from turning into a timing oracle.
    7. Allowlist check (FEAT-158), after credentials are confirmed valid:
       same placement as _handle_callback's is_email_allowed() call below
       — after identity is established, before a token is issued. Not
       strictly load-bearing on its own (get_current_user re-checks the
       allowlist on every authenticated request regardless of how the
       JWT was obtained), but issuing a 403 here instead of a 200 matches
       the OAuth path's behaviour exactly rather than silently diverging
       from it.
    """
    if not _password_auth_enabled():
        raise http_error(
            503,
            "password_auth_disabled",
            "Password authentication is disabled.",
        )

    email_norm = normalize_email(payload.email)

    await enforce_rate_limit(
        bucket="password_login",
        identity="global",
        # A CPU-flood backstop, not an account guard (see step 3 above) —
        # sized to only engage under a genuine flood, not casual retries.
        limit=100,
        window_seconds=60,
        message="Too many login attempts. Try again shortly.",
    )

    await lockout.assert_not_locked(email_norm)

    user = await authenticate_with_password(db, email_norm)

    if user is None or user.password_hash is None:
        await dummy_verify(payload.password)
        ok = False
    else:
        ok = await verify_password(payload.password, user.password_hash)

    if not ok or user is None:
        await lockout.record_failure(email_norm)
        raise http_error(401, "invalid_credentials", _INVALID_CREDENTIALS_MESSAGE)

    await lockout.clear_failures(email_norm)

    if not is_email_allowed(user.email):
        raise http_error(
            403,
            "email_not_allowed",
            "This deployment is restricted to its owner's account.",
        )

    token = encode_jwt(user.id)
    return {"data": {"token": token}}
