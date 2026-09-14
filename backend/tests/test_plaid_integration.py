"""Tests for PlaidIntegration — pasted-access-token validation and wiring.

_validate_pasted_access_token is pure (no DB, no httpx, no fixtures) and is
tested directly. The two connect()-level tests pin the wiring: the
validator is actually called, and the normalised (stripped) value is what
gets persisted — not the raw payload value.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal.plaid import (
    PlaidIntegration,
    _validate_pasted_access_token,
)

# ── _validate_pasted_access_token — pure unit tests ─────────────────────────


def test_valid_sandbox_token_accepted_and_returned(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    token = "access-sandbox-12345678-1234-1234-1234-123456789abc"

    result = _validate_pasted_access_token(token)

    assert result == token


def test_surrounding_whitespace_is_stripped_from_returned_token(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    token = "access-sandbox-12345678-1234-1234-1234-123456789abc"

    result = _validate_pasted_access_token(f"  {token}\n")

    assert result == token


def test_public_token_prefix_rejected():
    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token(
            "public-sandbox-12345678-1234-1234-1234-123456789abc"
        )

    assert exc_info.value.code == "invalid_api_key"


def test_missing_access_prefix_rejected():
    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token("sandbox-12345678-1234-1234-1234-123456789abc")

    assert exc_info.value.code == "invalid_api_key"


def test_too_short_rejected():
    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token("access-abc")

    assert exc_info.value.code == "invalid_api_key"


def test_too_long_rejected():
    token = "access-" + "x" * 494

    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token(token)

    assert exc_info.value.code == "invalid_api_key"


def test_whitespace_only_rejected():
    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token("   ")

    assert exc_info.value.code == "invalid_api_key"


def test_non_string_rejected():
    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token(123)

    assert exc_info.value.code == "invalid_api_key"


def test_internal_whitespace_rejected():
    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token("access-sandbox-uuid uuid-1234-1234-1234")

    assert exc_info.value.code == "invalid_api_key"


def test_control_character_rejected():
    token = "access-sandbox-1234\x005678-1234-1234-1234-123456789abc"

    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token(token)

    assert exc_info.value.code == "invalid_api_key"


def test_env_mismatch_rejected(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    token = "access-production-12345678-1234-1234-1234-123456789abc"

    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token(token)

    assert exc_info.value.code == "invalid_api_key"
    assert "production" in str(exc_info.value)
    assert "sandbox" in str(exc_info.value)


def test_unknown_env_segment_accepted(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    token = "access-enterprise-1234567890123456789012"

    result = _validate_pasted_access_token(token)

    assert result == token


@pytest.mark.parametrize(
    "bad_token",
    [
        "public-sandbox-12345678-1234-1234-1234-123456789abc",
        "sandbox-12345678-1234-1234-1234-123456789abc",
        "access-abc",
        "access-" + "x" * 494,
        "access-sandbox-uuid uuid-1234-1234-1234",
    ],
)
def test_error_message_never_echoes_token(bad_token):
    with pytest.raises(IntegrationError) as exc_info:
        _validate_pasted_access_token(bad_token)

    assert bad_token not in str(exc_info.value)


# ── connect() — wiring tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_stores_normalised_token(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    provider = PlaidIntegration()
    user = MagicMock()
    user.id = uuid.uuid4()
    token = "access-sandbox-12345678-1234-1234-1234-123456789abc"

    store_api_key = AsyncMock(return_value=MagicMock())
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_api_key)

    await provider.connect(
        user=user, db=MagicMock(), payload={"api_key": f"  {token}\n"}
    )

    store_api_key.assert_awaited_once()
    assert store_api_key.await_args.kwargs["api_key"] == token


@pytest.mark.asyncio
async def test_connect_rejects_bad_paste_without_storing(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    provider = PlaidIntegration()
    user = MagicMock()
    user.id = uuid.uuid4()

    store_api_key = AsyncMock(return_value=MagicMock())
    import src.integrations.personal.plaid as plaid_mod

    monkeypatch.setattr(plaid_mod, "store_api_key", store_api_key)

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(
            user=user, db=MagicMock(), payload={"api_key": "public-sandbox-abc"}
        )

    assert exc_info.value.code == "invalid_api_key"
    store_api_key.assert_not_awaited()
