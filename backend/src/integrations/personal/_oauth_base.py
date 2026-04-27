"""Generic OAuth integration provider base.

Each provider declares its config (auth_url, token_url, scopes, env-var
names for client_id/secret) and a fetch_profile() method. The shared
connect/exchange/store flow handles state, token exchange, and encrypted
storage. The generic /api/v1/integrations/oauth/{slug}/callback endpoint
routes back to the provider via the registry.

Required env vars (per provider):
  <SLUG_UPPER>_CLIENT_ID
  <SLUG_UPPER>_CLIENT_SECRET
  BACKEND_URL  (already set; used to build the redirect URI)
  FRONTEND_URL (already set; redirect target after success)
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import decrypt, encrypt
from ...middleware.cache import get_redis
from ...models.integration import Integration, IntegrationOAuthToken
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)

_STATE_TTL_SECONDS = 600  # 10 min — generous for slow consent flows


def _backend_url() -> str:
    return os.environ["BACKEND_URL"].rstrip("/")


def _frontend_url() -> str:
    return os.environ["FRONTEND_URL"].rstrip("/")


def _state_key(state: str) -> str:
    return f"int_oauth_state:{state}"


async def store_oauth_state(*, user_id: str, slug: str) -> str:
    """Generate a CSRF-protection state token, store user_id+slug in Redis."""
    state = secrets.token_urlsafe(32)
    redis = await get_redis()
    await redis.set(_state_key(state), f"{user_id}::{slug}", ex=_STATE_TTL_SECONDS)
    return state


async def consume_oauth_state(state: str) -> tuple[str, str] | None:
    """Atomically read+delete state. Returns (user_id, slug) or None."""
    redis = await get_redis()
    raw = await redis.getdel(_state_key(state))
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if "::" not in raw:
        return None
    user_id, slug = raw.split("::", 1)
    return user_id, slug


class OAuthIntegrationProvider(IntegrationProvider):
    """Subclasses declare:

      auth_url, token_url, scopes, client_id_env, client_secret_env
      Optional: additional_auth_params, profile_url, scope_separator

    And implement:
      async def fetch_profile(self, access_token) -> dict[str, Any]
      async def sync(self, *, integration, db) -> SyncResult
    """

    kind = "personal_oauth"
    auth_url: ClassVar[str]
    token_url: ClassVar[str]
    scopes: ClassVar[list[str]]
    client_id_env: ClassVar[str]
    client_secret_env: ClassVar[str]
    additional_auth_params: ClassVar[dict[str, str]] = {}
    scope_separator: ClassVar[str] = " "
    use_basic_auth_for_token: ClassVar[bool] = False

    def _redirect_uri(self) -> str:
        return f"{_backend_url()}/api/v1/integrations/oauth/{self.slug}/callback"

    def _client_id(self) -> str:
        val = os.getenv(self.client_id_env)
        if not val:
            raise IntegrationError(
                "missing_client_id",
                f"{self.client_id_env} not set on the backend. "
                f"Register an OAuth app at {self.docs_url} and add the env var to Render.",
            )
        return val

    def _client_secret(self) -> str:
        val = os.getenv(self.client_secret_env)
        if not val:
            raise IntegrationError(
                "missing_client_secret",
                f"{self.client_secret_env} not set on the backend.",
            )
        return val

    async def connect(
        self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
    ) -> ConnectResult:
        if user is None:
            raise IntegrationError("auth_required", "User context required.")
        # Validate config now so we surface a clear error before redirecting
        self._client_id()
        self._client_secret()
        state = await store_oauth_state(user_id=str(user.id), slug=self.slug)
        params = {
            "client_id": self._client_id(),
            "redirect_uri": self._redirect_uri(),
            "response_type": "code",
            "scope": self.scope_separator.join(self.scopes),
            "state": state,
            **self.additional_auth_params,
        }
        url = f"{self.auth_url}?{urlencode(params)}"
        return ConnectResult(integration_id="", redirect_url=url)

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """POST to token_url with code → returns the JSON token response."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri(),
        }
        if self.use_basic_auth_for_token:
            auth = (self._client_id(), self._client_secret())
            kwargs: dict[str, Any] = {"auth": auth}
        else:
            data["client_id"] = self._client_id()
            data["client_secret"] = self._client_secret()
            kwargs = {}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.token_url,
                data=data,
                headers={"Accept": "application/json"},
                **kwargs,
            )
        if resp.status_code >= 400:
            raise IntegrationError(
                "token_exchange_failed",
                f"{self.display_name} token exchange returned {resp.status_code}: {resp.text[:200]}",
            )
        return resp.json()

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        """Subclasses override. Default returns an empty dict."""
        return {}

    async def status(
        self, *, integration: Integration, db: AsyncSession
    ) -> StatusReport:
        token_row = await db.scalar(
            select(IntegrationOAuthToken).where(
                IntegrationOAuthToken.integration_id == integration.id
            )
        )
        extra: dict[str, Any] = dict(integration.config or {})
        if token_row is not None:
            extra["scopes"] = list(token_row.scopes or [])
            if token_row.expires_at:
                extra["expires_at"] = token_row.expires_at.isoformat()
        return StatusReport(
            status=integration.status,  # type: ignore[arg-type]
            last_synced_at=(
                integration.last_synced_at.isoformat()
                if integration.last_synced_at
                else None
            ),
            last_error=integration.last_error,
            extra=extra,
        )

    async def get_access_token(
        self, *, integration: Integration, db: AsyncSession
    ) -> str:
        """Decrypt the stored access token. Auto-refresh if expired and
        a refresh_token is available.
        """
        row = await db.scalar(
            select(IntegrationOAuthToken).where(
                IntegrationOAuthToken.integration_id == integration.id
            )
        )
        if row is None:
            raise IntegrationError(
                "not_connected", f"{self.display_name} OAuth tokens not stored."
            )
        if (
            row.expires_at
            and row.expires_at < datetime.now(timezone.utc) + timedelta(seconds=30)
            and row.encrypted_refresh_token
        ):
            await self._refresh(row=row, db=db)
        return decrypt(row.encrypted_access_token)

    async def _refresh(self, *, row: IntegrationOAuthToken, db: AsyncSession) -> None:
        rt = (
            decrypt(row.encrypted_refresh_token)
            if row.encrypted_refresh_token
            else None
        )
        if not rt:
            raise IntegrationError(
                "no_refresh_token",
                f"{self.display_name} access token expired and no refresh token is stored.",
            )
        data: dict[str, Any] = {
            "grant_type": "refresh_token",
            "refresh_token": rt,
        }
        if self.use_basic_auth_for_token:
            kwargs: dict[str, Any] = {
                "auth": (self._client_id(), self._client_secret())
            }
        else:
            data["client_id"] = self._client_id()
            data["client_secret"] = self._client_secret()
            kwargs = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.token_url,
                data=data,
                headers={"Accept": "application/json"},
                **kwargs,
            )
        if resp.status_code >= 400:
            raise IntegrationError(
                "refresh_failed",
                f"{self.display_name} refresh failed: {resp.status_code}",
            )
        body = resp.json()
        row.encrypted_access_token = encrypt(body["access_token"])
        if "refresh_token" in body:
            row.encrypted_refresh_token = encrypt(body["refresh_token"])
        if "expires_in" in body:
            row.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(body["expires_in"])
            )
        await db.commit()


async def upsert_oauth_integration(
    *,
    user_id: str,
    slug: str,
    db: AsyncSession,
    token_response: dict[str, Any],
    profile: dict[str, Any],
    scopes: list[str],
) -> Integration:
    """Create or update the integration + IntegrationOAuthToken rows
    after a successful code exchange.
    """
    import uuid

    user_uuid = uuid.UUID(user_id)
    integration = await db.scalar(
        select(Integration).where(
            Integration.user_id == user_uuid, Integration.slug == slug
        )
    )
    if integration is None:
        integration = Integration(
            user_id=user_uuid,
            slug=slug,
            kind="personal_oauth",
            status="connected",
            config={"profile": profile},
        )
        db.add(integration)
        await db.flush()
    else:
        integration.status = "connected"
        integration.last_error = None
        integration.config = {**(integration.config or {}), "profile": profile}

    token_row = await db.scalar(
        select(IntegrationOAuthToken).where(
            IntegrationOAuthToken.integration_id == integration.id
        )
    )
    expires_at = None
    if "expires_in" in token_response:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(token_response["expires_in"])
        )

    enc_access = encrypt(token_response["access_token"])
    enc_refresh = (
        encrypt(token_response["refresh_token"])
        if token_response.get("refresh_token")
        else None
    )

    if token_row is None:
        token_row = IntegrationOAuthToken(
            integration_id=integration.id,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            expires_at=expires_at,
            scopes=scopes,
            extra={"granted_at": time.time()},
        )
        db.add(token_row)
    else:
        token_row.encrypted_access_token = enc_access
        if enc_refresh is not None:
            token_row.encrypted_refresh_token = enc_refresh
        token_row.expires_at = expires_at
        token_row.scopes = scopes
        token_row.extra = {**(token_row.extra or {}), "granted_at": time.time()}

    await db.commit()
    await db.refresh(integration)
    return integration


def make_oauth_sync_via_api(
    *,
    sync_url: str,
    parse_sync: Any,
    summary_fmt: str = "{name}: refreshed",
):
    """Helper for OAuth providers whose sync just calls a single API endpoint
    with the bearer token and stores parse_sync(body) in integration.config.
    """

    async def _sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        access_token = await self.get_access_token(integration=integration, db=db)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    sync_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            integration.status = "error"
            integration.last_error = f"{type(exc).__name__}: {exc}"[:500]
            await db.commit()
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        integration.config = {
            **(integration.config or {}),
            **(parse_sync(body) if parse_sync else {"ok": True}),
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=summary_fmt.format(name=self.display_name),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    return _sync
