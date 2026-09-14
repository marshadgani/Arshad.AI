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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Literal
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


# How a provider's revocation endpoint wants to be called. There is an
# RFC for this (7009) and roughly half the providers here follow it; the
# rest each invented their own, so the shape has to be declared per
# provider. Naming the styles — rather than letting each provider
# hand-roll an httpx call — keeps the one part that must not be got wrong
# (reading and decrypting the stored token, failing open on error) in a
# single place.
#
#   rfc7009       POST, form-encoded `token=`, client credentials attached
#                 the same way the token grant attaches them.
#   query_token   POST with `?access_token=` in the query string (Strava,
#                 Oura). No client credentials.
#   bearer_delete DELETE with `Authorization: Bearer <token>` (Whoop,
#                 Upstox) — "delete my access", addressed by the token
#                 itself.
#   bearer_post   POST with `Authorization: Bearer <token>` (Linear).
RevokeStyle = Literal["rfc7009", "query_token", "bearer_delete", "bearer_post"]


class OAuthIntegrationProvider(IntegrationProvider):
    """Subclasses declare:

      auth_url, token_url, scopes, client_id_env, client_secret_env
      Optional: additional_auth_params, profile_url, scope_separator
      Optional: revoke_url + revoke_style — see _revoke_upstream() below

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
    # None = this provider publishes no revocation endpoint, and must say
    # so via `upstream_revocation = cannot_revoke(...)`. The two are kept
    # consistent by _assert_revocation_config_matches_claim() below.
    revoke_url: ClassVar[str | None] = None
    revoke_style: ClassVar[RevokeStyle] = "rfc7009"

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

    async def _revoke_upstream(
        self, *, integration: Integration, db: AsyncSession
    ) -> None:
        """Ask the provider to stop honouring this integration's tokens.

        Shared by every OAuth provider that sets `revoke_url`; they get
        working revocation by declaring a URL and a style rather than by
        each writing their own httpx call and each getting the
        fail-open/decrypt/absent-row edge cases subtly different.

        Three deliberate choices:

        * **The refresh token is revoked first, when there is one.** With
          every provider here that issues one, revoking the refresh token
          invalidates the whole grant including access tokens minted from
          it; revoking only the access token would leave a credential
          that can mint a new one. Both are attempted because "revoking
          the refresh token cascades" is a convention, not a guarantee,
          and these calls are idempotent.
        * **The two attempts are independent.** A failed refresh-token
          revocation must not skip the access-token one. Not every
          provider accepts both kinds at its endpoint — the `query_token`
          style (Strava, Oura) has no `token_type_hint` to offer and
          simply posts whatever it is given as `access_token`, so
          presenting a refresh token there is rejected. Aborting on that
          rejection left the *access* token live at the provider while
          the local copy was deleted and the dialog had already promised
          "revoked with the provider" — a silent false promise, which is
          the exact failure this feature exists to remove. The first
          failure is re-raised only after both attempts have been made,
          so disconnect() still logs that something went wrong.
        * **A missing token row is success, not an error.** disconnect()
          is idempotent by design (a double-click, a retry after a failed
          local delete), and the second call has nothing left to present.
        * **Decryption failure is not fatal.** After an
          OAUTH_ENCRYPTION_KEY rotation the ciphertext is unreadable —
          documented and expected (CLAUDE.md §6). The right outcome is
          still to delete the local rows, so this raises and disconnect()
          logs and continues, exactly as it does for an unreachable
          provider.

        Errors propagate to disconnect(), which logs and proceeds with
        local deletion — the user asked us to forget the credential, and
        a third party being down cannot veto that.
        """
        if self.revoke_url is None:
            return None

        tokens = await self._stored_tokens(integration=integration, db=db)
        if tokens is None:
            return None
        access_token, refresh_token = tokens

        failures: list[IntegrationError] = []
        if refresh_token:
            failures += await self._try_revocation(
                refresh_token, token_type_hint="refresh_token"
            )
        failures += await self._try_revocation(
            access_token, token_type_hint="access_token"
        )
        if failures:
            raise failures[0]

    async def _try_revocation(
        self, token: str, *, token_type_hint: str
    ) -> list[IntegrationError]:
        """One revocation attempt, reported rather than raised.

        Only IntegrationError is collected: that is the single type
        _post_revocation() raises, and it is the only one already known to
        be credential-free (see its docstring). Anything else is
        unexpected and propagates immediately rather than being folded
        into a list and re-raised out of its original context.
        """
        try:
            await self._post_revocation(token, token_type_hint=token_type_hint)
        except IntegrationError as exc:
            return [exc]
        return []

    async def _stored_tokens(
        self, *, integration: Integration, db: AsyncSession
    ) -> tuple[str, str | None] | None:
        """(access_token, refresh_token) in cleartext, or None if no row.

        Separate from get_access_token() because that method refreshes an
        expired token — the last thing wanted on the disconnect path,
        where the goal is to destroy the grant, not renew it. Both values
        are read and decrypted up front so the session is not left in use
        while a revocation request is in flight (database.md).

        Shared with providers whose revocation call is too idiosyncratic
        for `revoke_style` (see ZerodhaKiteIntegration), so they override
        only the request shape, not the credential handling.
        """
        row = await db.scalar(
            select(IntegrationOAuthToken).where(
                IntegrationOAuthToken.integration_id == integration.id
            )
        )
        if row is None:
            return None
        return (
            decrypt(row.encrypted_access_token),
            decrypt(row.encrypted_refresh_token)
            if row.encrypted_refresh_token
            else None,
        )

    async def _post_revocation(self, token: str, *, token_type_hint: str) -> None:
        """Issue one revocation call in this provider's declared style.

        A failure is raised, not swallowed — disconnect() must be able to
        log *that* the provider refused — but it is raised as an
        IntegrationError carrying only the upstream status code, never the
        httpx exception.

        That is not tidiness, it is the same rule `safe_detail()` in
        base.py exists for. httpx puts the full request URL in the message
        of both HTTPStatusError and RequestError, and the `query_token`
        style (Strava, Oura) puts the access token *in that URL*. Letting
        httpx's exception reach disconnect(), which logs it with
        `exc_info=True`, would write a live OAuth token into the Render
        application log in cleartext — defeating the AES-GCM-at-rest
        design one line before the token is deleted. `from None` matters
        for the same reason: a chained `__cause__` would put the original
        message back into the traceback.
        """
        url = self.revoke_url
        if url is None:  # unreachable via _revoke_upstream; belt and braces
            return

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = await self._send_revocation(client, url, token, token_type_hint)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise IntegrationError(
                "revoke_failed",
                f"{self.display_name} revocation returned {exc.response.status_code}.",
            ) from None
        except httpx.HTTPError as exc:
            raise IntegrationError(
                "revoke_failed",
                f"{self.display_name} revocation failed: {type(exc).__name__}.",
            ) from None

    async def _send_revocation(
        self,
        client: httpx.AsyncClient,
        url: str,
        token: str,
        token_type_hint: str,
    ) -> httpx.Response:
        """The request shape for each `revoke_style`, and nothing else.

        Split from _post_revocation so that the credential-safe error
        handling wraps every style uniformly — a style added here cannot
        accidentally bypass it.
        """
        if self.revoke_style == "rfc7009":
            data = {"token": token, "token_type_hint": token_type_hint}
            if self.use_basic_auth_for_token:
                return await client.post(
                    url, data=data, auth=(self._client_id(), self._client_secret())
                )
            return await client.post(
                url,
                data={
                    **data,
                    "client_id": self._client_id(),
                    "client_secret": self._client_secret(),
                },
            )
        if self.revoke_style == "query_token":
            return await client.post(url, params={"access_token": token})
        if self.revoke_style == "bearer_delete":
            return await client.delete(
                url, headers={"Authorization": f"Bearer {token}"}
            )
        return await client.post(url, headers={"Authorization": f"Bearer {token}"})

    # This override is real, but it only *does* anything when the subclass
    # also sets revoke_url — so on its own it must not be mistaken for
    # evidence that the provider revokes upstream. registry.register()
    # reads this marker to tell "overrode the hook" apart from "overrode
    # the hook and supplied what it needs", and rejects a provider
    # claiming revokes_via(...) on the strength of the former alone.
    _revoke_upstream.requires_attr = "revoke_url"  # type: ignore[attr-defined]

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
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
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
