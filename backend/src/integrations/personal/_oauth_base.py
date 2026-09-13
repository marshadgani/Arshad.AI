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

import json
import logging
import os
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import TokenDecryptError, decrypt, encrypt
from ...middleware.cache import get_redis
from ...models.integration import Integration, IntegrationOAuthToken
from ...models.user import User
from ..base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
    needs_reauth,
)

_STATE_TTL_SECONDS = 600  # 10 min — generous for slow consent flows

# Every outbound provider call from this module (token grants, sync reads).
_HTTP_TIMEOUT_SECONDS = 15.0

_log = logging.getLogger(__name__)


def _backend_url() -> str:
    return os.environ["BACKEND_URL"].rstrip("/")


def _frontend_url() -> str:
    return os.environ["FRONTEND_URL"].rstrip("/")


def _state_key(state: str) -> str:
    return f"int_oauth_state:{state}"


async def store_oauth_state(
    *, user_id: str, slug: str, ctx: dict[str, Any] | None = None
) -> str:
    """Generate a CSRF-protection state token, store user_id+slug in Redis.

    ctx carries provider-specific data (e.g. Shopify's shop domain) that must
    survive the round trip to the OAuth consent screen and back. When absent
    (every provider before Shopify), the stored value is the original plain
    "user_id::slug" string — no extra Redis round trip, fully backward
    compatible with consume_oauth_state's legacy fallback below.
    """
    state = secrets.token_urlsafe(32)
    pair = f"{user_id}::{slug}"
    value = json.dumps({"v": pair, "ctx": ctx}) if ctx else pair
    redis = await get_redis()
    await redis.set(_state_key(state), value, ex=_STATE_TTL_SECONDS)
    return state


def _unwrap_state_value(raw: str) -> tuple[str, dict[str, Any]]:
    """Split a stored state value into its "user_id::slug" pair and its ctx.

    Handles both shapes store_oauth_state writes: the JSON envelope (a
    provider passed ctx=...) and the legacy plain string, which has no ctx.
    """
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw, {}
    if isinstance(envelope, dict) and "v" in envelope:
        return str(envelope["v"]), dict(envelope.get("ctx") or {})
    return raw, {}


async def consume_oauth_state(state: str) -> tuple[str, str, dict[str, Any]] | None:
    """Atomically read+delete state. Returns (user_id, slug, ctx) or None.

    Tries the JSON envelope first (providers that called store_oauth_state
    with ctx=...), falling back to the legacy plain "user_id::slug" string
    with ctx={} for every other provider's state key.
    """
    redis = await get_redis()
    raw = await redis.getdel(_state_key(state))
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    pair, ctx = _unwrap_state_value(raw)
    if "::" not in pair:
        return None
    user_id, slug = pair.split("::", 1)
    return user_id, slug, ctx


@dataclass(frozen=True)
class OAuthCallbackContext:
    """Everything complete_callback() needs beyond the provider instance."""

    code: str
    state: str
    user_id: str
    query_params: Mapping[str, str]
    stored: Mapping[str, Any]


@dataclass(frozen=True)
class CallbackOutcome:
    token_response: dict[str, Any]
    profile: dict[str, Any] = field(default_factory=dict)
    config_extra: dict[str, Any] = field(default_factory=dict)


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
        return ConnectResult(integration_id=None, redirect_url=url)

    async def _post_token_request(self, data: dict[str, str]) -> httpx.Response:
        """POST a grant to token_url with this provider's client credentials
        attached the way it expects — HTTP Basic, or in the form body.

        Shared by the initial code exchange and the refresh grant, which
        differ only in their form fields and in what they report on failure,
        so the caller owns the error message for a non-2xx response.
        """
        if self.use_basic_auth_for_token:
            kwargs: dict[str, Any] = {
                "auth": (self._client_id(), self._client_secret())
            }
        else:
            data = {
                **data,
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
            }
            kwargs = {}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            return await client.post(
                self.token_url,
                data=data,
                headers={"Accept": "application/json"},
                **kwargs,
            )

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """POST to token_url with code → returns the JSON token response."""
        resp = await self._post_token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri(),
            }
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

    async def complete_callback(
        self, *, context: OAuthCallbackContext
    ) -> CallbackOutcome:
        """Handle the OAuth callback for this provider.

        Default implementation is a lift-and-shift of the standard
        Authorization Code flow: exchange the code, best-effort fetch the
        profile (a failure here must not fail the whole callback), and
        return with no extra config. Providers with a non-standard callback
        (per-shop token URLs, signature verification, etc. — see
        ShopifyIntegration) override this instead of hand-rolling their own
        router wiring.
        """
        token_response = await self.exchange_code(context.code)
        access_token = token_response.get("access_token")
        if not access_token:
            raise IntegrationError(
                "no_access_token", "Provider returned no access_token."
            )
        try:
            profile = await self.fetch_profile(access_token)
        except Exception as exc:  # noqa: BLE001 — fetch_profile is best-effort
            _log.warning(
                "fetch_profile failed for %s: %s", self.slug, type(exc).__name__
            )
            profile = {}
        return CallbackOutcome(token_response=token_response, profile=profile)

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

    def sync_headers(self, access_token: str) -> dict[str, str]:
        """Request headers for this provider's sync read.

        The overwhelming majority of providers are plain bearer-token, so
        that is the default. A provider whose API authenticates
        differently (Kite wants `token <api_key>:<access_token>` plus a
        version header) overrides this instead of re-implementing sync().

        Called by make_oauth_sync_via_api inside its guarded block, so an
        override that touches config -- e.g. `self._client_id()`, which
        raises IntegrationError('missing_client_id') when the env var is
        unset or rotated -- is classified by record_sync_failure like any
        other sync failure rather than escaping unclassified and leaving
        integration.status stuck at its previous value.
        """
        return {"Authorization": f"Bearer {access_token}"}

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
        try:
            return decrypt(row.encrypted_access_token)
        except TokenDecryptError as exc:
            # Corrupted ciphertext or a rotated OAUTH_ENCRYPTION_KEY makes
            # this row permanently unusable -- no retry will ever succeed.
            # Bare TokenDecryptError is invisible to integrations.base.
            # needs_reauth (it only recognises IntegrationError and
            # httpx.HTTPStatusError), so left unwrapped it was classified
            # as a transient 'error' by record_sync_failure even though
            # "token_decryption_failed" is already declared in REAUTH_CODES
            # for exactly this case. Wrapping it here is what makes that
            # declared code actually reachable, and turns the wire message
            # from the misleading "Try syncing again" into "Reconnect".
            raise IntegrationError(
                "token_decryption_failed",
                f"{self.display_name} access token could not be decrypted.",
            ) from exc

    async def _refresh(self, *, row: IntegrationOAuthToken, db: AsyncSession) -> None:
        try:
            rt = (
                decrypt(row.encrypted_refresh_token)
                if row.encrypted_refresh_token
                else None
            )
        except TokenDecryptError as exc:
            raise IntegrationError(
                "token_decryption_failed",
                f"{self.display_name} refresh token could not be decrypted.",
            ) from exc
        if not rt:
            raise IntegrationError(
                "no_refresh_token",
                f"{self.display_name} access token expired and no refresh token is stored.",
            )
        resp = await self._post_token_request(
            {"grant_type": "refresh_token", "refresh_token": rt}
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
    config_extra: dict[str, Any] | None = None,
) -> Integration:
    """Create or update the integration + IntegrationOAuthToken rows
    after a successful code exchange.

    config_extra is merged into integration.config alongside 'profile' —
    e.g. Shopify's shop_domain/shop_timezone/currency_code, which no other
    provider needs, so this stays an opt-in kwarg with no effect on the
    15 existing providers, which never pass it.
    """
    user_uuid = uuid.UUID(user_id)
    extra = config_extra or {}
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
            config={"profile": profile, **extra},
        )
        db.add(integration)
        await db.flush()
    else:
        integration.status = "connected"
        integration.last_error = None
        integration.config = {
            **(integration.config or {}),
            "profile": profile,
            **extra,
        }

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


_LAST_ERROR_MAX_CHARS = 500


async def record_sync_failure(
    integration: Integration,
    exc: BaseException,
    db: AsyncSession,
    *,
    slug: str,
    extra_codes: frozenset[str] = frozenset(),
) -> bool:
    """Classify `exc` and persist the resulting status on `integration`.

    Returns the needs_reauth bool so the caller can shape its own error
    message. Never raises — a failure to persist status must not mask the
    original sync failure the caller is about to re-raise. The raw
    exception text is written to Integration.last_error (truncated, DB-only
    — never serialised to the client, see services/finance/holdings.py) and
    logged here, since that log line is the only remaining signal once the
    wire response is sanitised.
    """
    reauth = needs_reauth(exc, extra_codes)
    try:
        integration.status = "expired" if reauth else "error"
        integration.last_error = f"{type(exc).__name__}: {exc}"[:_LAST_ERROR_MAX_CHARS]
        _log.warning(
            "sync failed slug=%s status=%s err=%s: %s",
            slug,
            integration.status,
            type(exc).__name__,
            exc,
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        _log.exception("Failed to persist sync failure status for slug=%s", slug)
    return reauth


ParseSync = Callable[[Any], dict[str, Any]]
Summarise = Callable[[str, dict[str, Any]], str]
SyncMethod = Callable[..., Awaitable[SyncResult]]


def make_oauth_sync_via_api(
    *,
    sync_url: str,
    parse_sync: ParseSync | None,
    summary_fmt: str = "{name}: refreshed",
    summarise: Summarise | None = None,
    extra_reauth_codes: frozenset[str] = frozenset(),
) -> SyncMethod:
    """Helper for OAuth providers whose sync just calls a single API endpoint
    and stores parse_sync(body) in integration.config.

    This is the one implementation of the sync lifecycle -- preflight
    token, guarded read, failure classification, config merge, commit --
    and therefore the one place the "never leave integration.status stuck
    at its previous value" invariant has to hold. Providers vary only in
    what they declare: the URL, how the body parses, how the request
    authenticates (OAuthIntegrationProvider.sync_headers), and what the
    summary line says.

    `summarise` takes (display_name, config_update) and exists for
    providers whose summary quotes something the parse produced (a row
    count). Without it, `summary_fmt` is formatted with the display name.
    """

    async def _sync(self, *, integration: Integration, db: AsyncSession) -> SyncResult:
        started = time.perf_counter()
        # Every step that can fail is inside this one guarded block, which is
        # what enforces the invariant above: the preflight token fetch, the
        # header build (an override such as Kite's sync_headers reads provider
        # config and can raise), the HTTP read, and the parse of a possibly
        # malformed upstream body. Anything left outside would propagate
        # unclassified and strand integration.status at its previous value.
        try:
            access_token = await self.get_access_token(integration=integration, db=db)
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.get(
                    sync_url,
                    headers=self.sync_headers(access_token),
                )
                resp.raise_for_status()
                body = resp.json()
            config_update = parse_sync(body) if parse_sync else {"ok": True}
        except Exception as exc:  # noqa: BLE001
            reauth = await record_sync_failure(
                integration, exc, db, slug=self.slug, extra_codes=extra_reauth_codes
            )
            # The message on this exception is rendered verbatim by
            # integrations/routers.py into a 400 error envelope, i.e. it is
            # wire-facing. The raw exception text (class name, upstream URL,
            # upstream status/body fragment) must never go there per
            # .claude/rules/api.md -- it is already persisted to
            # Integration.last_error and logged by record_sync_failure above,
            # which are the diagnostic channels. Two generic sentences, chosen
            # by the same reauth classification the status column uses, so the
            # client still learns whether reconnecting will help.
            raise IntegrationError(
                "sync_failed",
                (
                    f"Your {self.display_name} connection expired. "
                    "Reconnect it and try again."
                    if reauth
                    else f"Couldn't reach {self.display_name}. Try syncing again."
                ),
            ) from exc
        integration.config = {
            **(integration.config or {}),
            **config_update,
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=(
                summarise(self.display_name, config_update)
                if summarise
                else summary_fmt.format(name=self.display_name)
            ),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    return _sync
