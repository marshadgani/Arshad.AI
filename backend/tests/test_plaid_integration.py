"""Tests for PlaidIntegration — direct-paste api_key validation and connect().

Mirrors test_shopify_integration.py's style: direct provider instantiation
with monkeypatched collaborators, no HTTP server, zero network calls.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal import plaid_client
from src.integrations.personal.plaid import PlaidIntegration, _validate_access_token

# ── Helpers ───────────────────────────────────────────────────────────────────


def _set_plaid_backend_creds(monkeypatch, env: str = "sandbox") -> None:
    monkeypatch.setenv("PLAID_ENV", env)
    monkeypatch.setenv("PLAID_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PLAID_SECRET", "test-secret")


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


# ── _validate_access_token ───────────────────────────────────────────────────


def test_validate_accepts_sandbox_token(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")

    result = _validate_access_token("access-sandbox-abc123")

    assert result == "access-sandbox-abc123"


def test_validate_accepts_development_token(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "development")

    result = _validate_access_token("access-development-abc123")

    assert result == "access-development-abc123"


def test_validate_accepts_production_token(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "production")

    result = _validate_access_token("access-production-abc123")

    assert result == "access-production-abc123"


def test_validate_rejects_unknown_prefix(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")

    with pytest.raises(IntegrationError) as exc_info:
        _validate_access_token("not-a-plaid-token")

    assert exc_info.value.code == "invalid_access_token_format"


def test_validate_rejects_public_token_with_hint(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")

    with pytest.raises(IntegrationError) as exc_info:
        _validate_access_token("public-sandbox-abc123")

    assert exc_info.value.code == "invalid_access_token_format"
    assert "public_token" in exc_info.value.message


def test_validate_rejects_env_mismatch(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")

    with pytest.raises(IntegrationError) as exc_info:
        _validate_access_token("access-production-abc123")

    assert exc_info.value.code == "plaid_env_mismatch"


def test_validate_rejects_empty_remainder(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")

    with pytest.raises(IntegrationError) as exc_info:
        _validate_access_token("access-sandbox-")

    assert exc_info.value.code == "invalid_access_token_format"


def test_validate_rejects_internal_whitespace(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")

    with pytest.raises(IntegrationError):
        _validate_access_token("access-sandbox-abc def")


def test_validate_rejects_control_character(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")

    with pytest.raises(IntegrationError):
        _validate_access_token("access-sandbox-abc\x00def")


# ── connect — api_key (direct paste) branch ─────────────────────────────────


@pytest.mark.asyncio
async def test_connect_strips_surrounding_whitespace(monkeypatch):
    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()
    user = _make_user()

    store_mock = AsyncMock()
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_mock)

    await provider.connect(
        user=user, db=MagicMock(), payload={"api_key": "  access-sandbox-abc\n"}
    )

    assert store_mock.await_args.kwargs["api_key"] == "access-sandbox-abc"


@pytest.mark.asyncio
async def test_connect_invalid_key_never_stores(monkeypatch):
    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()
    user = _make_user()

    store_mock = AsyncMock()
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_mock)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(
            user=user, db=MagicMock(), payload={"api_key": "not-a-plaid-token"}
        )

    assert exc_info.value.code == "invalid_access_token_format"
    store_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_missing_backend_creds_raises_before_store(monkeypatch):
    """B1 regression: this test fails on the pre-change code, which called
    store_api_key() for the api_key branch without ever checking that
    PLAID_CLIENT_ID/PLAID_SECRET are configured."""
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
    monkeypatch.delenv("PLAID_SECRET", raising=False)
    provider = PlaidIntegration()
    user = _make_user()

    store_mock = AsyncMock()
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_mock)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(
            user=user, db=MagicMock(), payload={"api_key": "access-sandbox-abc123"}
        )

    assert exc_info.value.code == "plaid_not_configured"
    store_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_checks_backend_creds_before_validating_token_format(
    monkeypatch,
):
    """Gate-ordering invariant (REQ-PLAID-001, REQ-PLAID-002):
    require_backend_config() fires BEFORE _validate_access_token(), so when
    BOTH the deployment is unconfigured AND the pasted token is syntactically
    invalid, the raised error is 'plaid_not_configured' (a deployment-operator
    error), NOT 'invalid_access_token_format' (a user error).

    This prevents surfacing a misleading user-facing error that prompts the
    user to fix their token when the real problem is a missing env var.

    Combines missing creds (B1 trigger) with a syntactically-wrong token
    (B3 trigger) to verify that B1 wins — the only possible outcome if the
    require_backend_config() call precedes _validate_access_token() in the
    implementation.
    """
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
    monkeypatch.delenv("PLAID_SECRET", raising=False)
    provider = PlaidIntegration()
    user = _make_user()

    store_mock = AsyncMock()
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_mock)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(
            user=user,
            db=MagicMock(),
            payload={"api_key": "not-a-plaid-token-at-all"},
        )

    # B1 gate must win — deployment config error, not user token error
    assert exc_info.value.code == "plaid_not_configured", (
        f"Expected 'plaid_not_configured' (B1 gate) but got "
        f"'{exc_info.value.code}' — require_backend_config() must be called "
        "BEFORE _validate_access_token() in _connect_via_pasted_token()."
    )
    store_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_missing_both_tokens_still_raises_missing_token(monkeypatch):
    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()
    user = _make_user()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=user, db=MagicMock(), payload={})

    assert exc_info.value.code == "missing_token"


@pytest.mark.asyncio
async def test_connect_whitespace_only_api_key_raises_missing_api_key(monkeypatch):
    """Edge: a truthy-but-blank api_key ("   ") passes the `if payload.get(
    "api_key")` truthiness check in connect() and only gets caught inside
    require_api_key() — must not slip through as an empty/valid token."""
    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()
    user = _make_user()

    store_mock = AsyncMock()
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_mock)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=user, db=MagicMock(), payload={"api_key": "   "})

    assert exc_info.value.code == "missing_api_key"
    store_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_valid_api_key_store_called_with_cleaned_token(monkeypatch):
    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()
    user = _make_user()

    store_mock = AsyncMock()
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_mock)

    await provider.connect(
        user=user, db=MagicMock(), payload={"api_key": "access-sandbox-abc123"}
    )

    store_mock.assert_awaited_once()
    assert store_mock.await_args.kwargs["api_key"] == "access-sandbox-abc123"
    assert store_mock.await_args.kwargs["extra"]["source"] == "direct_paste"


@pytest.mark.asyncio
async def test_error_messages_contain_no_token_material(monkeypatch):
    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()
    user = _make_user()

    secret_fragment = "zzTOPSECRETzz"
    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(
            user=user,
            db=MagicMock(),
            payload={"api_key": f"access-sandbox-{secret_fragment}\x00tail"},
        )

    assert secret_fragment not in exc_info.value.message


@pytest.mark.asyncio
async def test_public_token_branch_unchanged(monkeypatch):
    """Regression pin: public_token exchange is deliberately NOT routed
    through _validate_access_token — Plaid's own response is authoritative."""
    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()
    user = _make_user()

    store_mock = AsyncMock()
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_mock)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "access-sandbox-fromplaid",
        "item_id": "item-1",
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # httpx now lives in plaid_client — the transport module the provider
    # delegates to — so the patch targets it there.
    import src.integrations.personal.plaid_client as plaid_client_mod

    monkeypatch.setattr(
        plaid_client_mod.httpx, "AsyncClient", MagicMock(return_value=mock_client)
    )

    await provider.connect(
        user=user, db=MagicMock(), payload={"public_token": "public-sandbox-xyz"}
    )

    store_mock.assert_awaited_once()
    assert store_mock.await_args.kwargs["api_key"] == "access-sandbox-fromplaid"


# ── plaid_env() resolution ───────────────────────────────────────────────────
# PLAID_ENV feeds two things at once: the host label in base_url() and the
# right-hand side of the env comparison in validate_access_token(). These pin
# that it is normalised and allowlisted before either consumer sees it.


@pytest.mark.parametrize("raw", ["sandbox\n", "  sandbox  ", "SANDBOX", "Sandbox\t"])
def test_plaid_env_normalises_whitespace_and_case(monkeypatch, raw):
    """Regression: a PLAID_ENV pasted into the Render dashboard with a
    trailing newline (or odd casing) must still resolve to a clean env.

    Before normalisation this produced BOTH a malformed host
    ('https://sandbox\\n.plaid.com') and an unfalsifiable-looking error —
    "token is for 'sandbox' but backend is configured for PLAID_ENV='sandbox'"
    — because the newline is invisible in the rendered message.
    """
    monkeypatch.setenv("PLAID_ENV", raw)

    assert plaid_client.plaid_env() == "sandbox"
    assert plaid_client.base_url() == "https://sandbox.plaid.com"
    # And a legitimate token for that env is no longer falsely rejected.
    assert _validate_access_token("access-sandbox-abc") == "access-sandbox-abc"


def test_plaid_env_defaults_to_sandbox_when_unset(monkeypatch):
    """Backward-compat pin: an unset PLAID_ENV keeps defaulting to sandbox."""
    monkeypatch.delenv("PLAID_ENV", raising=False)

    assert plaid_client.plaid_env() == "sandbox"


@pytest.mark.parametrize("raw", ["prod", "staging", ""])
def test_plaid_env_rejects_unknown_environment(monkeypatch, raw):
    """An env Plaid publishes no host for is an operator error, surfaced as
    'plaid_not_configured' rather than left to fail as a DNS error mid-sync."""
    monkeypatch.setenv("PLAID_ENV", raw)

    with pytest.raises(IntegrationError) as exc_info:
        plaid_client.base_url()

    assert exc_info.value.code == "plaid_not_configured"


@pytest.mark.parametrize(
    "hostile", ["evil.com/", "sandbox.plaid.com.attacker.net/", "../../evil.com/"]
)
def test_plaid_env_cannot_relocate_the_request_host(monkeypatch, hostile):
    """Security pin: PLAID_ENV is interpolated into the request host, so an
    unconstrained value can move the request off plaid.com entirely —
    PLAID_ENV='evil.com/' yields host 'evil.com' — which would POST
    PLAID_CLIENT_ID, PLAID_SECRET and the user's bank access_token to it.
    The allowlist must reject these before any URL is built.
    """
    import httpx

    monkeypatch.setenv("PLAID_ENV", hostile)

    with pytest.raises(IntegrationError) as exc_info:
        url = plaid_client.base_url()
        # Only reached on regression; make the failure state the real damage.
        raise AssertionError(
            f"PLAID_ENV={hostile!r} built {url!r} with host "
            f"{httpx.URL(url).host!r} — credentials would leave plaid.com."
        )

    assert exc_info.value.code == "plaid_not_configured"


def test_plaid_env_error_message_does_not_echo_the_bad_value(monkeypatch):
    """The operator-facing message names the variable, not the value: an
    unvalidated PLAID_ENV is attacker-shaped input in the host position and
    must not be reflected back into a response body."""
    monkeypatch.setenv("PLAID_ENV", "evil.com/")

    with pytest.raises(IntegrationError) as exc_info:
        plaid_client.plaid_env()

    assert "evil.com" not in exc_info.value.message
    assert "PLAID_ENV" in exc_info.value.message


@pytest.mark.asyncio
async def test_sync_reports_bad_env_as_config_error_not_user_sync_failure(monkeypatch):
    """Invariant guard: a deployment fault must not be written to this user's
    Integration row as a sync error.

    sync() calls require_backend_config() before its try-block for exactly
    this reason, so that gate must cover PLAID_ENV too — otherwise a bad env
    is first discovered inside base_url(), which on the sync path is reached
    from within the try and lands in integration.last_error.
    """
    monkeypatch.setenv("PLAID_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("PLAID_SECRET", "test-secret")
    monkeypatch.setenv("PLAID_ENV", "prod")
    provider = PlaidIntegration()

    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(
        provider, "_stored_access_token", AsyncMock(return_value="access-sandbox-abc")
    )
    mark_error_mock = AsyncMock()
    monkeypatch.setattr(plaid_mod, "mark_error", mark_error_mock)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.sync(integration=MagicMock(), db=MagicMock())

    assert exc_info.value.code == "plaid_not_configured"
    mark_error_mock.assert_not_awaited()


# ── description / sync() alignment ───────────────────────────────────────────
# Mirrors test_shopify_integration.test_description_does_not_claim_sync_does_
# live_data: the same over-promising defect existed here, so it gets the same
# guard.


def test_description_does_not_promise_transactions():
    """The user-facing description must not claim capabilities no code path
    delivers.

    It previously read "US bank accounts, balances, transactions via Plaid
    Link" while nothing in the package ever called /transactions/get — sync()
    fetches /accounts/get only, and unlike Shopify there is no live-read
    dashboard endpoint serving them either.

    If a real transactions read path is added, update this test deliberately
    rather than loosening it.
    """
    provider = PlaidIntegration()

    approved_description = "US bank accounts and balances via Plaid Link."

    assert provider.description == approved_description, (
        f"PlaidIntegration.description changed.\n"
        f"  Got:      {provider.description!r}\n"
        f"  Expected: {approved_description!r}\n"
        "Confirm the new text does not promise data no code path fetches."
    )
    assert "transaction" not in provider.description.lower(), (
        "PlaidIntegration.description promises transactions, but no code "
        "path calls /transactions/get. Implement it or drop the claim."
    )


def test_declared_scopes_match_what_sync_exercises():
    """scopes are echoed back as extra['scopes'], so they are a claim about
    this integration's reach — they must not over-declare either."""
    from src.integrations.personal.plaid import _SCOPES

    assert _SCOPES == ["accounts:read"], (
        f"_SCOPES is {_SCOPES!r}. sync() calls /accounts/get only; declaring "
        "a scope no code exercises overstates the integration's reach."
    )


# ── SEC: credential / PII leakage and unbounded input ────────────────────────


@pytest.mark.asyncio
async def test_sync_failure_message_does_not_echo_the_request_url(monkeypatch):
    """SEC-001 regression: the sync_failed message becomes the 400 body of
    POST /api/v1/integrations/plaid/sync, and httpx embeds the full request
    URL — and therefore any query-string credential — in the message of
    every HTTPStatusError. It must carry safe_detail(exc) only.
    """
    import httpx

    _set_plaid_backend_creds(monkeypatch)
    provider = PlaidIntegration()

    import src.integrations.personal.plaid as plaid_mod

    leaky_url = "https://sandbox.plaid.com/accounts/get?secret=zzTOPSECRETzz"
    request = httpx.Request("POST", leaky_url)
    leaky = httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(429, request=request)
    )

    monkeypatch.setattr(
        provider, "_stored_access_token", AsyncMock(return_value="access-sandbox-abc")
    )
    monkeypatch.setattr(plaid_mod, "mark_error", AsyncMock())
    monkeypatch.setattr(
        plaid_mod.plaid_client, "fetch_accounts", AsyncMock(side_effect=leaky)
    )

    with pytest.raises(IntegrationError) as exc_info:
        await provider.sync(integration=MagicMock(), db=MagicMock())

    assert exc_info.value.code == "sync_failed"
    assert "zzTOPSECRETzz" not in exc_info.value.message
    assert "429" in exc_info.value.message


@pytest.mark.asyncio
async def test_disconnect_clears_the_stored_account_snapshot(monkeypatch):
    """SEC-002 regression: scrub_credentials() removes credentials only, so
    the bank account names/types/balances sync() caches in
    Integration.config survived 'disconnect' forever. Disconnecting a bank
    must not leave cleartext financial detail in Postgres.
    """
    from src.integrations.base import IntegrationProvider

    provider = PlaidIntegration()
    integration = MagicMock()
    integration.config = {
        "env": "sandbox",
        "account_count": 2,
        "accounts": [{"name": "Plaid Checking", "balance": 110.0}],
    }
    db = MagicMock()
    db.commit = AsyncMock()

    monkeypatch.setattr(IntegrationProvider, "disconnect", AsyncMock())

    await provider.disconnect(integration=integration, db=db)

    assert "accounts" not in integration.config
    assert "account_count" not in integration.config
    assert integration.config["env"] == "sandbox"


def test_validate_rejects_oversized_token(monkeypatch):
    """Input validation at the trust boundary: /connect must not encrypt and
    persist an arbitrarily large pasted blob."""
    from src.integrations.personal.plaid_tokens import MAX_ACCESS_TOKEN_CHARS

    monkeypatch.setenv("PLAID_ENV", "sandbox")

    with pytest.raises(IntegrationError) as exc_info:
        _validate_access_token("access-sandbox-" + "a" * MAX_ACCESS_TOKEN_CHARS)

    assert exc_info.value.code == "invalid_access_token_format"
