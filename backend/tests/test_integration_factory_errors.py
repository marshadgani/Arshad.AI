"""Regression tests for FEAT-146 — provider parse_probe/parse_sync failures
must surface as a clean IntegrationError (HTTP 400), never an unhandled 500.

Drives the REAL Slack provider through the REAL factory (make_provider) with
a patched httpx.AsyncClient — parse_probe/parse_sync are exercised as wired,
not monkeypatched directly. Generic guard behaviour (any provider's parse
raising a bare exception, or its own IntegrationError, or a raising
parse_sync) is covered with synthetic ProviderSpec instances built the same
way bulk_providers.py builds real ones, so the registry is never mutated.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.auth.dependencies import get_current_user
from src.integrations.base import ConnectResult, IntegrationError
from src.integrations.project._factory import ProviderSpec, make_provider
from src.main import app
from src.models.database import get_db

USER_ID = uuid.uuid4()


# ── shared test doubles ──────────────────────────────────────────────────


class _FakeUser:
    id = USER_ID
    email = "m.arshadgani@gmail.com"


class _FakeIntegration:
    def __init__(self, slug: str = "slack", status: str = "connected"):
        self.id = uuid.uuid4()
        self.slug = slug
        self.user_id = USER_ID
        self.status = status
        self.last_error = None
        self.config = {}


class _FakeResponse:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._body


class _FakeAsyncClient:
    """Replaces httpx.AsyncClient in the _factory module namespace.

    Returns a fixed response for every .get() call regardless of URL —
    sufficient because these tests each drive a single outbound request.
    """

    def __init__(self, response: _FakeResponse):
        self._response = response

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        return self._response


def _patch_client(monkeypatch, status_code: int, body: Any):
    import src.integrations.project._factory as factory_module

    monkeypatch.setattr(
        factory_module.httpx,
        "AsyncClient",
        _FakeAsyncClient(_FakeResponse(status_code, body)),
    )


def _make_db():
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def client_factory(monkeypatch):
    """Returns a function that builds a TestClient wired to a given provider
    slug -> provider instance mapping, with auth/db overridden."""

    def _build(providers: dict[str, Any]):
        import src.integrations.routers as routers_module

        async def _override_user():
            return _FakeUser()

        async def _override_db():
            yield _make_db()

        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[get_db] = _override_db
        monkeypatch.setattr(routers_module, "INTEGRATION_REGISTRY", providers)
        monkeypatch.setattr(
            routers_module, "get_provider", lambda slug: providers.get(slug)
        )
        return TestClient(app)

    yield _build
    app.dependency_overrides.clear()


# ── T1: Slack connect ok:false → 400, never 500 (regression contract) ─────


def test_slack_connect_ok_false_returns_400_not_500(client_factory, monkeypatch):
    from src.integrations.project.bulk_providers import _SlackProvider

    _patch_client(monkeypatch, 200, {"ok": False, "error": "invalid_auth"})
    tc = client_factory({"slack": _SlackProvider()})

    resp = tc.post("/api/v1/integrations/slack/connect", json={"api_key": "xoxb-fake"})

    assert resp.status_code != 500
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == "invalid_key"
    assert "Slack" in error["message"]
    assert "invalid_auth" in error["message"]


# ── T2: Slack connect ok:true succeeds, team/user carried through ─────────


def test_slack_connect_ok_true_succeeds_with_team_and_user(client_factory, monkeypatch):
    from src.integrations.project.bulk_providers import _SlackProvider

    _patch_client(monkeypatch, 200, {"ok": True, "team": "T1", "user": "U1"})

    import src.integrations.project._factory as factory_module

    store_mock = AsyncMock(
        return_value=ConnectResult(integration_id="int-1", redirect_url=None)
    )
    monkeypatch.setattr(factory_module, "store_api_key", store_mock)

    tc = client_factory({"slack": _SlackProvider()})

    resp = tc.post("/api/v1/integrations/slack/connect", json={"api_key": "xoxb-real"})

    assert resp.status_code == 200
    assert resp.json()["data"]["integration_id"] == "int-1"
    assert store_mock.await_args.kwargs["extra"] == {"team": "T1", "user": "U1"}


# ── T3: generic factory guard — bare exception → probe_parse_failed ───────


@pytest.mark.asyncio
async def test_generic_probe_parse_bare_exception_becomes_integration_error(
    monkeypatch,
):
    def _raises(body):
        raise ValueError("boom")

    spec = ProviderSpec(
        slug="synthetic",
        display_name="Synthetic",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
        parse_probe=_raises,
    )
    provider_cls = make_provider(spec)
    provider = provider_cls()

    _patch_client(monkeypatch, 200, {})

    with pytest.raises(IntegrationError) as excinfo:
        await provider._probe("key")

    assert excinfo.value.code == "probe_parse_failed"
    assert not isinstance(excinfo.value, ValueError)


# ── T4: pass-through — provider's own IntegrationError survives verbatim ──


@pytest.mark.asyncio
async def test_generic_probe_parse_integration_error_passes_through_unchanged(
    monkeypatch,
):
    def _rejects(body):
        raise IntegrationError("custom_code", "custom msg")

    spec = ProviderSpec(
        slug="synthetic2",
        display_name="Synthetic2",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
        parse_probe=_rejects,
    )
    provider = make_provider(spec)()

    _patch_client(monkeypatch, 200, {})

    with pytest.raises(IntegrationError) as excinfo:
        await provider._probe("key")

    assert excinfo.value.code == "custom_code"
    assert excinfo.value.message == "custom msg"


# ── T5: sync path — raising parse_sync yields IntegrationError + marks error ─


@pytest.mark.asyncio
async def test_sync_parse_bare_exception_marks_integration_error(monkeypatch):
    import src.integrations.project._factory as factory_module

    def _raises(body):
        raise KeyError("missing")

    spec = ProviderSpec(
        slug="synthetic3",
        display_name="Synthetic3",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
        parse_sync=_raises,
    )
    provider = make_provider(spec)()

    fake_creds = MagicMock()
    fake_creds.encrypted_key = "blob"
    db = MagicMock()
    db.scalar = AsyncMock(return_value=fake_creds)
    db.commit = AsyncMock()

    monkeypatch.setattr(factory_module, "decrypt", lambda blob: "plaintext-key")
    _patch_client(monkeypatch, 200, {"some": "body"})

    integration = _FakeIntegration(slug="synthetic3")
    original_config = dict(integration.config)

    with pytest.raises(IntegrationError) as excinfo:
        await provider.sync(integration=integration, db=db)

    assert excinfo.value.code == "sync_parse_failed"
    assert integration.status == "error"
    assert integration.last_error
    assert integration.config == original_config  # no partial merge persisted


# ── T6: sync pass-through IntegrationError also marks error ───────────────


@pytest.mark.asyncio
async def test_sync_parse_integration_error_passes_through_and_marks_error(
    monkeypatch,
):
    import src.integrations.project._factory as factory_module

    def _rejects(body):
        raise IntegrationError("invalid_key", "revoked")

    spec = ProviderSpec(
        slug="synthetic4",
        display_name="Synthetic4",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
        parse_sync=_rejects,
    )
    provider = make_provider(spec)()

    fake_creds = MagicMock()
    fake_creds.encrypted_key = "blob"
    db = MagicMock()
    db.scalar = AsyncMock(return_value=fake_creds)
    db.commit = AsyncMock()

    monkeypatch.setattr(factory_module, "decrypt", lambda blob: "plaintext-key")
    _patch_client(monkeypatch, 200, {"some": "body"})

    integration = _FakeIntegration(slug="synthetic4")

    with pytest.raises(IntegrationError) as excinfo:
        await provider.sync(integration=integration, db=db)

    assert excinfo.value.code == "invalid_key"
    assert excinfo.value.message == "revoked"
    assert integration.status == "error"


# ── T7: no-regression — a non-Slack provider's probe is unaffected ────────


@pytest.mark.asyncio
async def test_generic_probe_happy_path_unchanged(monkeypatch):
    spec = ProviderSpec(
        slug="synthetic5",
        display_name="Synthetic5",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
        parse_probe=lambda body: {"count": len(body or [])},
    )
    provider = make_provider(spec)()

    _patch_client(monkeypatch, 200, [1, 2, 3])

    result = await provider._probe("key")

    assert result == {"count": 3}
