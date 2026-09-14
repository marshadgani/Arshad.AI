"""Tests for the Slack parse_probe/parse_sync bare-Exception fix and the
_run_parser boundary in _factory.py.

httpx.AsyncClient is patched at the module level rather than injected —
_factory.py constructs it inline, with no seam — so these exercise the
pieces that matter: the parser itself and the control flow around it.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.auth.crypto import TokenDecryptError
from src.integrations.base import IntegrationError, cannot_revoke
from src.integrations.project._factory import ProviderSpec, _run_parser, make_provider
from src.integrations.project.bulk_providers import _slack_identity

# ── _slack_identity (pure unit) ────────────────────────────────────────────


def test_slack_identity_raises_integration_error_on_not_ok():
    with pytest.raises(IntegrationError) as exc_info:
        _slack_identity({"ok": False, "error": "invalid_auth"})
    assert exc_info.value.code == "invalid_key"
    assert "invalid_auth" in exc_info.value.message


def test_slack_identity_returns_identity_on_ok():
    result = _slack_identity({"ok": True, "team": "T1", "user": "U1"})
    assert result == {"team": "T1", "user": "U1"}


def test_slack_identity_handles_non_dict_body():
    for body in (None, [], "not-a-dict"):
        with pytest.raises(IntegrationError) as exc_info:
            _slack_identity(body)  # type: ignore[arg-type]
        assert exc_info.value.code == "invalid_key"


# ── _run_parser (pure unit) ─────────────────────────────────────────────────


def test_run_parser_translates_bare_exception():
    def _raising_parser(body):
        raise ValueError("boom")

    with pytest.raises(IntegrationError) as exc_info:
        _run_parser(_raising_parser, {}, display_name="X", stage="probe")
    assert exc_info.value.code == "probe_failed"
    assert "boom" not in exc_info.value.message

    with pytest.raises(IntegrationError) as exc_info:
        _run_parser(_raising_parser, {}, display_name="X", stage="sync")
    assert exc_info.value.code == "sync_failed"

    assert _run_parser(None, {}, display_name="X", stage="probe") == {"ok": True}


def test_run_parser_does_not_rewrap_integration_error():
    def _raising_parser(body):
        raise IntegrationError("invalid_key", "m")

    with pytest.raises(IntegrationError) as exc_info:
        _run_parser(_raising_parser, {}, display_name="X", stage="probe")
    assert exc_info.value.code == "invalid_key"


# ── connect()/_probe boundary ──────────────────────────────────────────────


def _slack_spec() -> ProviderSpec:
    return ProviderSpec(
        slug="test-slack",
        display_name="Test Slack",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {"Authorization": f"Bearer {key}"},
        parse_probe=_slack_identity,
        parse_sync=_slack_identity,
        per_user=True,
        upstream_revocation=cannot_revoke("Test spec revokes nothing upstream."),
    )


def _fake_client(resp) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_connect_translates_non_json_probe_body():
    """A 2xx body that isn't JSON must surface as IntegrationError, not a 500:
    connect() only translates IntegrationError and httpx.HTTPError, and
    Response.json() raises ValueError (json.JSONDecodeError), which is neither.
    """
    provider = make_provider(_slack_spec())()

    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(side_effect=ValueError("Expecting value"))

    with patch(
        "src.integrations.project._factory.httpx.AsyncClient",
        return_value=_fake_client(resp),
    ):
        with pytest.raises(IntegrationError) as exc_info:
            await provider.connect(
                user=MagicMock(id=uuid.uuid4()),
                db=MagicMock(),
                payload={"api_key": "k"},
            )
    assert exc_info.value.code == "probe_failed"


@pytest.mark.asyncio
async def test_connect_rejects_missing_user_before_probing():
    """per_user providers must fail auth before any network call or key read."""
    provider = make_provider(_slack_spec())()

    with patch("src.integrations.project._factory.httpx.AsyncClient") as client_cls:
        with pytest.raises(IntegrationError) as exc_info:
            await provider.connect(user=None, db=MagicMock(), payload={"api_key": "k"})
    assert exc_info.value.code == "auth_required"
    client_cls.assert_not_called()


# ── sync() control-flow (integration-ish, monkeypatched httpx + db) ────────


class _FakeCreds:
    encrypted_key = b"irrelevant"


class _FakeIntegration:
    def __init__(self):
        self.id = uuid.uuid4()
        self.status = "connected"
        self.last_error = None
        self.last_synced_at = "2026-01-01T00:00:00+00:00"
        self.config = {"team": "old"}


@pytest.mark.asyncio
async def test_sync_marks_error_and_preserves_code_when_parser_raises():
    provider = make_provider(_slack_spec())()

    integration = _FakeIntegration()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=_FakeCreds())
    db.commit = AsyncMock()

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"ok": False, "error": "token_revoked"})

    with (
        patch(
            "src.integrations.project._factory.httpx.AsyncClient",
            return_value=_fake_client(resp),
        ),
        patch(
            "src.integrations.project._shared.decrypt",
            return_value="fake-token",
        ),
    ):
        with pytest.raises(IntegrationError) as exc_info:
            await provider.sync(integration=integration, db=db)

    assert exc_info.value.code == "invalid_key"
    assert integration.status == "error"
    assert integration.last_synced_at == "2026-01-01T00:00:00+00:00"
    assert integration.config == {"team": "old"}


# ── credential-read boundary ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_translates_undecryptable_key_instead_of_raising_500():
    """A stored key that will not decrypt must surface as IntegrationError.

    Same defect class as the original Slack bug, at a different site:
    `decrypt` raises TokenDecryptError (a plain Exception), and
    _stored_api_key runs *before* sync()'s try block, so nothing in the
    factory or the router translated it — it reached FastAPI as a 500.
    Rotating OAUTH_ENCRYPTION_KEY makes every stored key undecryptable,
    so this is a documented operational event, not a hypothetical.
    """
    provider = make_provider(_slack_spec())()

    db = MagicMock()
    db.scalar = AsyncMock(return_value=_FakeCreds())
    db.commit = AsyncMock()

    with patch(
        "src.integrations.project._shared.decrypt",
        side_effect=TokenDecryptError("ciphertext failed AES-GCM authentication"),
    ):
        with pytest.raises(IntegrationError) as exc_info:
            await provider.sync(integration=_FakeIntegration(), db=db)

    assert exc_info.value.code == "not_connected"
    # The ciphertext diagnostic describes our storage, not the user's
    # problem, and must not be echoed to the client.
    assert "AES-GCM" not in exc_info.value.message
    assert "reconnect" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_sync_reports_not_connected_when_no_credential_row_exists():
    """The other half of the credential-read contract: a missing row and an
    unreadable row are indistinguishable to the user and share one code."""
    provider = make_provider(_slack_spec())()

    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.commit = AsyncMock()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.sync(integration=_FakeIntegration(), db=db)

    assert exc_info.value.code == "not_connected"


# ── preload_api_key_credentials — N+1 fix ───────────────────────────────────
#
# GET /api/v1/integrations fans out over every registered provider
# (bulk_providers.py alone adds 10) and, before this fix, project_status()
# issued one ApiKeyCredential SELECT per provider on every page load.
# preload_api_key_credentials() batches that into a single query and caches
# the result on db.info for the rest of the request.


class _FakeCredentialRow:
    def __init__(self, integration_id, key_prefix="ab***"):
        self.integration_id = integration_id
        self.key_prefix = key_prefix
        self.scopes = ["read"]
        self.extra = {"team": "T1"}


@pytest.mark.asyncio
async def test_preload_api_key_credentials_issues_one_batched_query():
    from src.integrations.project._shared import preload_api_key_credentials

    ids = [uuid.uuid4() for _ in range(5)]
    rows = [_FakeCredentialRow(i) for i in ids[:3]]  # 2 of the 5 have no row

    db = MagicMock()
    db.info = {}
    scalars_result = MagicMock()
    scalars_result.all.return_value = rows
    db.scalars = AsyncMock(return_value=scalars_result)

    await preload_api_key_credentials(db, ids)

    db.scalars.assert_awaited_once()
    cache = db.info["_api_key_credentials_by_integration"]
    for i in ids[:3]:
        assert cache[i] is rows[ids.index(i)]
    for i in ids[3:]:
        assert cache[i] is None


@pytest.mark.asyncio
async def test_preload_api_key_credentials_skips_query_when_fully_cached():
    """A second preload call for ids already cached must not re-query —
    this is what makes it safe to call repeatedly within one request
    without reverting to the original N+1 behaviour."""
    from src.integrations.project._shared import preload_api_key_credentials

    shared_id = uuid.uuid4()
    db = MagicMock()
    db.info = {}
    scalars_result = MagicMock()
    scalars_result.all.return_value = [_FakeCredentialRow(shared_id)]
    db.scalars = AsyncMock(return_value=scalars_result)

    await preload_api_key_credentials(db, [shared_id])
    await preload_api_key_credentials(db, [shared_id])

    db.scalars.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_status_uses_preloaded_cache_without_querying():
    """project_status() must read from the batch-loaded cache instead of
    issuing its own per-integration SELECT once preload has populated it."""
    from src.integrations.project._shared import (
        preload_api_key_credentials,
        project_status,
    )

    integration = _FakeIntegration()
    integration.last_synced_at = None
    db = MagicMock()
    db.info = {}
    scalars_result = MagicMock()
    scalars_result.all.return_value = [_FakeCredentialRow(integration.id)]
    db.scalars = AsyncMock(return_value=scalars_result)
    db.scalar = AsyncMock(
        side_effect=AssertionError("project_status must not fall back to db.scalar")
    )

    await preload_api_key_credentials(db, [integration.id])
    report = await project_status(integration=integration, db=db)

    assert report.extra["key_prefix"] == "ab***"
    assert report.extra["team"] == "T1"
    db.scalar.assert_not_awaited()
