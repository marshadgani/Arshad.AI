"""End-to-end tests for the Slack provider's error-handling fix (FEAT-088:
parse_probe/parse_sync raising bare Exception instead of IntegrationError).

This is the layer test_integrations_factory.py deliberately does not cover:
it exercises the ACTUAL registered 'slack' ProviderSpec (imported from
bulk_providers.py, loaded into the real registry) through the full request
stack for both HTTP boundaries the bug could surface at:

    TestClient
    -> POST /api/v1/integrations/slack/connect  (probe path)
    -> POST /api/v1/integrations/slack/sync     (sync path)
    -> routers.py connect_integration() / sync_integration()
    -> registry.get('slack')  <- the REAL _SlackProvider from bulk_providers.py
    -> provider.connect() / provider.sync()
    -> httpx GET https://slack.com/api/auth.test  <- intercepted by respx
    -> _slack_identity(body)
    -> IntegrationError
    -> http_error(400)

Prior coverage (test_integrations_factory.py) unit-tests _slack_identity
and _run_parser directly, and drives connect()/sync() with a hand-rolled
ProviderSpec + monkeypatched httpx.AsyncClient. Neither touches the real
Slack registration, and neither goes through routers.py — so a regression
in the router's `except IntegrationError` wiring for either endpoint (e.g.
someone dropping that arm, or reordering it after a bare `except
Exception`) would pass every existing test while still returning 500 to a
real client. That is the gap this file closes.

Dependencies
------------
- respx >= 0.21 -- transport-level httpx mock (present in the environment;
  not currently pinned in backend/requirements.txt — see note in the PR).
- pytest-asyncio -- already used elsewhere in this suite.

DB and auth are stubbed via FastAPI dependency_overrides, following the
same pattern as test_integrations_router.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from src.auth.dependencies import get_current_user
from src.integrations.base import ConnectResult
from src.main import app
from src.models.database import get_db

# ── Constants ─────────────────────────────────────────────────────────────

SLACK_PROBE_URL = "https://slack.com/api/auth.test"
USER_ID = uuid.uuid4()
INTEGRATION_ID = uuid.uuid4()

# ── Test doubles ──────────────────────────────────────────────────────────


class _FakeUser:
    id = USER_ID


class _FakeIntegration:
    def __init__(self, status: str = "connected"):
        self.id = INTEGRATION_ID
        self.slug = "slack"
        self.user_id = USER_ID
        self.status = status
        self.last_error = None
        self.last_synced_at = None
        self.config = {}


class _FakeCreds:
    encrypted_key = b"irrelevant"


# ── Fixtures ───────────────────────────────────────────────────────────────


def _make_db(scalar_value=None):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=scalar_value)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Guarantee dependency_overrides are always cleaned up between tests."""
    yield
    app.dependency_overrides.clear()


def _make_client(db):
    """Build a TestClient wired to the REAL Slack provider from the registry.

    Auth and DB are stubbed; httpx transport is left open for respx to
    intercept — the client is used INSIDE a respx.mock() context in each
    test so the transport mock is active when the TestClient issues its call.
    """

    async def _override_user():
        return _FakeUser()

    async def _override_db():
        yield db

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db

    return TestClient(app)


# ── connect(): AC1/AC2/AC3 — Slack auth failure returns HTTP 400, not 500 ──


@respx.mock
def test_slack_connect_invalid_token_returns_400_not_500():
    """Slack's auth.test returns HTTP 200 with ok=false. Before the fix, the
    bare Exception this produced escaped _factory.py's connect() (which
    only translated IntegrationError/httpx.HTTPError) as an unhandled 500.
    """
    respx.get(SLACK_PROBE_URL).mock(
        return_value=Response(200, json={"ok": False, "error": "invalid_auth"})
    )

    db = _make_db()
    tc = _make_client(db)

    resp = tc.post(
        "/api/v1/integrations/slack/connect",
        json={"api_key": "xoxb-invalid-token"},
    )

    assert resp.status_code == 400, (
        f"Expected 400, got {resp.status_code}. Body: {resp.text}"
    )
    body = resp.json()
    assert body["error"]["code"] == "invalid_key", (
        f"Expected code='invalid_key', got {body['error']['code']!r}. "
        "The code must come from _slack_identity, not a generic 'probe_failed'."
    )


@pytest.mark.parametrize(
    "slack_error",
    ["invalid_auth", "token_revoked", "account_inactive", "not_authed"],
)
@respx.mock
def test_slack_connect_various_error_codes_all_return_invalid_key(slack_error):
    """All Slack API error values in ok=false responses map to code='invalid_key'
    — the machine-readable code is a closed vocabulary, Slack's own string
    only ever reaches the human-readable message."""
    respx.get(SLACK_PROBE_URL).mock(
        return_value=Response(200, json={"ok": False, "error": slack_error})
    )

    db = _make_db()
    tc = _make_client(db)

    resp = tc.post(
        "/api/v1/integrations/slack/connect",
        json={"api_key": "xoxb-some-token"},
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "invalid_key"
    assert slack_error in body["error"]["message"]


@respx.mock
def test_slack_connect_missing_api_key_returns_400_and_never_calls_slack():
    """require_api_key() raises before any HTTP call is made — the probe
    route must never be hit when api_key is absent from the payload."""
    probe_route = respx.get(SLACK_PROBE_URL).mock(
        return_value=Response(200, json={"ok": True, "team": "T1", "user": "U1"})
    )

    db = _make_db()
    tc = _make_client(db)

    resp = tc.post("/api/v1/integrations/slack/connect", json={})

    assert resp.status_code == 400
    assert probe_route.call_count == 0


@respx.mock
def test_slack_connect_valid_token_returns_200_with_identity():
    """Confirms the fix did not break the working path."""
    respx.get(SLACK_PROBE_URL).mock(
        return_value=Response(
            200, json={"ok": True, "team": "T12345", "user": "U67890"}
        )
    )

    db = _make_db(scalar_value=None)  # no existing integration -> new insert
    tc = _make_client(db)

    with patch(
        "src.integrations.project._factory.store_api_key",
        new=AsyncMock(
            return_value=ConnectResult(
                integration_id=str(INTEGRATION_ID), redirect_url=None
            )
        ),
    ):
        resp = tc.post(
            "/api/v1/integrations/slack/connect",
            json={"api_key": "xoxb-valid-token"},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["integration_id"] == str(INTEGRATION_ID)
    assert data["redirect_url"] is None


# ── sync(): the gap test_integrations_factory.py leaves — the real Slack
#    provider driven through POST /{slug}/sync, not called directly ────────


@respx.mock
def test_slack_sync_token_revoked_returns_400_not_500():
    """The sync-side mirror of test_slack_connect_invalid_token_returns_400_not_500.

    routers.py's sync_integration() has its own `except IntegrationError`
    arm, separate from connect_integration()'s — a regression there (e.g.
    reordering except arms, or dropping the catch) would not be caught by
    any connect-side test, including the ones above. This proves the real
    Slack provider's sync() failure reaches the client as a clean 400 via
    the actual /sync route, not just via calling provider.sync() in-process
    (which is all test_integrations_factory.py + the unit tests do).
    """
    respx.get(SLACK_PROBE_URL).mock(
        return_value=Response(200, json={"ok": False, "error": "token_revoked"})
    )

    integration = _FakeIntegration(status="connected")
    db = _make_db(scalar_value=_FakeCreds())
    tc = _make_client(db)

    with (
        patch(
            "src.integrations.routers._find_user_integration",
            new=AsyncMock(return_value=integration),
        ),
        patch(
            "src.integrations.project._shared.decrypt",
            return_value="xoxb-revoked-token",
        ),
    ):
        resp = tc.post("/api/v1/integrations/slack/sync")

    assert resp.status_code == 400, (
        f"Expected 400, got {resp.status_code}. Body: {resp.text}"
    )
    body = resp.json()
    assert body["error"]["code"] == "invalid_key"
    assert integration.status == "error"


@respx.mock
def test_slack_sync_valid_token_returns_200_and_merges_config():
    """Sync happy path through the real /sync route: existing config keys
    survive (merge, not replace) and the response reports completion."""
    respx.get(SLACK_PROBE_URL).mock(
        return_value=Response(200, json={"ok": True, "team": "T9999", "user": "U8888"})
    )

    integration = _FakeIntegration(status="connected")
    integration.config = {"pre_existing_key": "preserved_value"}
    db = _make_db(scalar_value=_FakeCreds())
    tc = _make_client(db)

    with (
        patch(
            "src.integrations.routers._find_user_integration",
            new=AsyncMock(return_value=integration),
        ),
        patch(
            "src.integrations.project._shared.decrypt",
            return_value="xoxb-valid-token",
        ),
    ):
        resp = tc.post("/api/v1/integrations/slack/sync")

    assert resp.status_code == 200
    assert integration.config.get("pre_existing_key") == "preserved_value"
    assert integration.config.get("team") == "T9999"
    assert integration.status == "connected"


@respx.mock
def test_slack_sync_when_not_connected_returns_400_and_never_calls_slack():
    """sync_integration() 400s on a missing integration row before any
    provider method (and therefore any HTTP call) runs."""
    probe_route = respx.get(SLACK_PROBE_URL).mock(
        return_value=Response(200, json={"ok": True, "team": "T1", "user": "U1"})
    )

    db = _make_db()
    tc = _make_client(db)

    with patch(
        "src.integrations.routers._find_user_integration",
        new=AsyncMock(return_value=None),
    ):
        resp = tc.post("/api/v1/integrations/slack/sync")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_connected"
    assert probe_route.call_count == 0
