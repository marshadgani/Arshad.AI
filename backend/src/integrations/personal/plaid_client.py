"""Plaid transport: environment resolution, backend credentials, and the two
HTTP calls the provider makes.

Split out of plaid.py so that plaid.py holds nothing but the integration
lifecycle (connect -> sync -> status). Everything that knows a Plaid URL, a
Plaid request body, or a Plaid response key lives here, so the provider never
handles raw Plaid JSON and a change to Plaid's wire format touches one file.

Two error conventions live side by side here, deliberately:

  * connect-time calls (exchange_public_token) raise IntegrationError, whose
    `code` the /connect response surfaces to the user directly;
  * sync-time calls (fetch_accounts) let httpx/decode errors propagate raw,
    because the provider's sync() records `type(exc).__name__` on the
    Integration row. Wrapping them here would flatten every distinct Plaid
    failure into the single label "IntegrationError" in last_error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from ..base import IntegrationError

_TIMEOUT_SECONDS = 15.0
_ERROR_BODY_MAX_CHARS = 200
_MAX_ACCOUNTS_STORED = 10

# The only values Plaid publishes an API host for. An allowlist rather than a
# sanity regex because this string is interpolated into the request host in
# base_url(): an unconstrained value can move the request off plaid.com
# entirely (PLAID_ENV='evil.com/' resolves to host 'evil.com'), which would
# POST PLAID_CLIENT_ID, PLAID_SECRET and the user's bank access_token to it.
_PLAID_ENVS = frozenset({"sandbox", "development", "production"})


@dataclass(frozen=True)
class TokenExchange:
    """Result of /item/public_token/exchange — the long-lived credential."""

    access_token: str
    item_id: str | None


def plaid_env() -> str:
    """The deployment's Plaid environment: sandbox | development | production.

    Normalised (stripped and lower-cased) and allowlisted, because this one
    string has two jobs that both need it to be trustworthy: it is the host
    label in base_url(), and it is the right-hand side of the environment
    comparison in plaid_tokens.validate_access_token().

    Normalisation is not cosmetic. A value pasted into the Render dashboard
    with a trailing newline used to produce the host 'sandbox\\n.plaid.com'
    AND an unfalsifiable-looking error — "this access_token is for the
    'sandbox' environment, but this backend is configured for
    PLAID_ENV='sandbox'" — because the newline is invisible in the rendered
    message. Both symptoms have the same cause and are fixed here rather
    than at either call site.
    """
    env = os.getenv("PLAID_ENV", "sandbox").strip().lower()
    if env not in _PLAID_ENVS:
        raise IntegrationError(
            "plaid_not_configured",
            "PLAID_ENV must be one of 'sandbox', 'development', or "
            "'production'. Fix the PLAID_ENV environment variable on the "
            "backend.",
        )
    return env


def base_url() -> str:
    return f"https://{plaid_env()}.plaid.com"


def require_backend_config() -> None:
    """Raise 'plaid_not_configured' unless the backend Plaid config is usable.

    Callers use this to surface a deployment-configuration error *before*
    entering a try-block that would otherwise record it against the user's
    Integration row as a per-user sync failure.

    Covers PLAID_ENV as well as the credentials so that sync()'s existing
    pre-try gate keeps that invariant whole: a bad PLAID_ENV is only
    discovered deeper in, inside base_url(), which on the sync path is
    reached from within the try and would otherwise be recorded as this
    user's integration failing rather than as the deployment fault it is.

    Credentials are checked first so that a deployment missing everything
    reports the missing-credentials error it always has.
    """
    _backend_credentials()
    plaid_env()


def _backend_credentials() -> dict[str, str]:
    cid = os.getenv("PLAID_CLIENT_ID")
    secret = os.getenv("PLAID_SECRET")
    if not cid or not secret:
        raise IntegrationError(
            "plaid_not_configured",
            "PLAID_CLIENT_ID and PLAID_SECRET must be set on the backend. "
            "Sign up at https://dashboard.plaid.com/signup.",
        )
    return {"client_id": cid, "secret": secret}


async def exchange_public_token(public_token: str) -> TokenExchange:
    """Exchange a Plaid Link public_token for a long-lived access_token."""
    creds = _backend_credentials()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{base_url()}/item/public_token/exchange",
                json={**creds, "public_token": public_token},
            )
        if resp.status_code >= 400:
            raise IntegrationError(
                "exchange_failed",
                f"Plaid token exchange returned {resp.status_code}: "
                f"{resp.text[:_ERROR_BODY_MAX_CHARS]}",
            )
        body = resp.json() or {}
    except IntegrationError:
        raise
    except httpx.HTTPError as exc:
        raise IntegrationError(
            "plaid_unreachable", f"Plaid API unreachable: {type(exc).__name__}"
        )

    access_token = body.get("access_token")
    if not access_token:
        raise IntegrationError(
            "no_access_token", "Plaid response missing access_token."
        )
    return TokenExchange(access_token=access_token, item_id=body.get("item_id"))


async def fetch_accounts(access_token: str) -> list[dict[str, Any]]:
    """Return the raw `accounts` array from /accounts/get.

    Transport and decode failures propagate untouched — see the module
    docstring for why this call does not raise IntegrationError.
    """
    creds = _backend_credentials()
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{base_url()}/accounts/get",
            json={**creds, "access_token": access_token},
        )
        resp.raise_for_status()
        body = resp.json() or {}
    return body.get("accounts") or []


async def remove_item(access_token: str) -> None:
    """Invalidate an access_token at Plaid via /item/remove.

    The only true revocation available for a Plaid credential, and the
    one that matters most in this codebase: an Item left in place keeps
    the bank connection live *and* keeps billing against it, so deleting
    only our encrypted copy would silently leave the user's bank linked
    to an app they believe they disconnected.

    Plaid treats removing an already-removed Item as an error
    (ITEM_NOT_FOUND); that is not a failure of the caller's intent, so it
    is reported as success to keep disconnect() idempotent. Every other
    failure propagates for disconnect() to log — transport errors
    included, deliberately raw, because this is the disconnect path and
    nothing here is echoed to the client.
    """
    creds = _backend_credentials()
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{base_url()}/item/remove",
            json={**creds, "access_token": access_token},
        )
    if resp.status_code == 200:
        return
    if _is_item_not_found(resp):
        return
    resp.raise_for_status()


def _is_item_not_found(resp: httpx.Response) -> bool:
    """Whether a non-200 /item/remove response means "already gone".

    Matched on Plaid's machine-readable `error_code`, never on the HTTP
    status or the human message — Plaid returns 400 for many unrelated
    reasons, and swallowing all of them would turn a genuinely failed
    revocation into a silent success.
    """
    try:
        return (resp.json() or {}).get("error_code") == "ITEM_NOT_FOUND"
    except ValueError:
        return False


def account_summaries(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project Plaid's account objects onto the subset stored in
    Integration.config.

    Capped because Integration.config is a status record rendered in the
    integrations UI, not an account ledger.
    """
    return [
        {
            "id": a.get("account_id"),
            "name": a.get("name"),
            "type": a.get("type"),
            "balance": (a.get("balances") or {}).get("current"),
            "currency": (a.get("balances") or {}).get("iso_currency_code"),
        }
        for a in accounts[:_MAX_ACCOUNTS_STORED]
    ]
