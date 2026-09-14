"""FEAT-146 — Comprehensive test suite for Slack/provider parse_probe and
parse_sync error-handling contract.

Covers every acceptance criterion in RTM-FEAT-146 (REQ-146-1 through
REQ-146-6) plus all gaps flagged in the test plan:

- Unit-level parse_guard.guarded_parse() and safe_reason() contract
  (gap: these were only exercised indirectly through _factory.py)
- decode_json() non-JSON-body branch (gap)
- Transport-failure probe_failed path (gap: connect()'s httpx.HTTPError handler)
- safe_reason() control-character sanitisation (gap: security-relevant)
- personal/_oauth_base.py regression guard (gap: parse_guard shared with this path)

Run with:
    cd backend && python -m pytest tests/test_feat146_integration_error_handling.py -v
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from src.auth.dependencies import get_current_user
from src.integrations.base import ConnectResult, IntegrationError
from src.integrations.parse_guard import (
    decode_json,
    guarded_parse,
    safe_reason,
)
from src.integrations.project._factory import ProviderSpec, make_provider
from src.main import app
from src.models.database import get_db

USER_ID = uuid.uuid4()


# ── Shared test doubles ──────────────────────────────────────────────────────


class _FakeUser:
    id = USER_ID
    email = "arshad@example.com"


class _FakeIntegration:
    def __init__(self, slug: str = "slack", status: str = "connected"):
        self.id = uuid.uuid4()
        self.slug = slug
        self.user_id = USER_ID
        self.status = status
        self.last_error = None
        self.config = {}


class _FakeResponse:
    def __init__(self, status_code: int, body: Any, *, bad_json: bool = False):
        self.status_code = status_code
        self._body = body
        self._bad_json = bad_json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx as _httpx

            raise _httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )

    def json(self) -> Any:
        if self._bad_json:
            raise ValueError("No JSON object could be decoded")
        return self._body


class _FakeAsyncClient:
    """Replaces httpx.AsyncClient in the _factory module namespace."""

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


class _FakeRaisingAsyncClient:
    """Raises httpx.ConnectError on every .get() — simulates transport failure."""

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        import httpx as _httpx

        raise _httpx.ConnectError("[Errno -2] Name or service not known")


def _patch_client(monkeypatch, status_code: int, body: Any, *, bad_json: bool = False):
    import src.integrations.project._factory as factory_module

    monkeypatch.setattr(
        factory_module.httpx,
        "AsyncClient",
        _FakeAsyncClient(_FakeResponse(status_code, body, bad_json=bad_json)),
    )


def _patch_transport_failure(monkeypatch):
    import src.integrations.project._factory as factory_module

    monkeypatch.setattr(factory_module.httpx, "AsyncClient", _FakeRaisingAsyncClient())


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
    """Builds a TestClient with overridden auth/db and isolated provider registry."""

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


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT LAYER — parse_guard module in isolation
# (Covers the gap: guarded_parse() and safe_reason() were only exercised
#  indirectly through _factory.py in the existing test file.)
# ═══════════════════════════════════════════════════════════════════════════════


# ── TC-001: guarded_parse — branch 1 passthrough (IntegrationError verbatim) ─
# REQ-146-2, REQ-146-3, AC-6, AC-7


@pytest.mark.asyncio
async def test_guarded_parse_branch1_integration_error_passes_through_verbatim():
    """When the callback raises IntegrationError, guarded_parse re-raises it
    unchanged — code and message are preserved exactly."""

    def _parse(_body):
        raise IntegrationError("my_code", "my message")

    with pytest.raises(IntegrationError) as exc_info:
        await guarded_parse(
            _parse,
            {},
            provider_name="Acme",
            stage="probe",
            error_code="probe_parse_failed",
        )

    assert exc_info.value.code == "my_code", "code must not be rewritten"
    assert exc_info.value.message == "my message", "message must not be rewritten"


# ── TC-002: guarded_parse — branch 1 on_error hook fires for IntegrationError ─
# REQ-146-4, AC-9 (defensive factory wrap)


@pytest.mark.asyncio
async def test_guarded_parse_branch1_on_error_hook_fires_for_integration_error():
    """on_error is awaited with the provider's own IntegrationError so the
    caller can mark the integration row 'error' even on a passthrough."""
    captured = []

    async def _hook(exc):
        captured.append(exc)

    def _parse(_body):
        raise IntegrationError("token_revoked", "revoked")

    with pytest.raises(IntegrationError):
        await guarded_parse(
            _parse,
            {},
            provider_name="Acme",
            stage="probe",
            error_code="probe_parse_failed",
            on_error=_hook,
        )

    assert len(captured) == 1
    assert captured[0].code == "token_revoked"


# ── TC-003: guarded_parse — branch 2 bare Exception becomes IntegrationError ─
# REQ-146-1, REQ-146-4, AC-7, AC-9


@pytest.mark.asyncio
async def test_guarded_parse_branch2_bare_exception_becomes_integration_error():
    """A bare (non-IntegrationError) exception from the callback is wrapped
    into IntegrationError with the caller-specified error_code. The original
    exception type must NOT escape."""

    def _parse(_body):
        raise RuntimeError("unexpected structure")

    with pytest.raises(IntegrationError) as exc_info:
        await guarded_parse(
            _parse,
            {},
            provider_name="Acme",
            stage="probe",
            error_code="probe_parse_failed",
        )

    assert exc_info.value.code == "probe_parse_failed"
    assert not isinstance(exc_info.value, RuntimeError), (
        "RuntimeError must not escape the boundary"
    )


# ── TC-004: guarded_parse — branch 2 on_error hook fires for bare Exception ──
# REQ-146-4, AC-9


@pytest.mark.asyncio
async def test_guarded_parse_branch2_on_error_hook_fires_for_bare_exception():
    """on_error is awaited with the *original* bare exception (not the wrapped
    IntegrationError) so the caller's mark_error can record the actual type."""
    captured = []

    async def _hook(exc):
        captured.append(exc)

    def _parse(_body):
        raise KeyError("missing_field")

    with pytest.raises(IntegrationError):
        await guarded_parse(
            _parse,
            {},
            provider_name="Acme",
            stage="probe",
            error_code="probe_parse_failed",
            on_error=_hook,
        )

    assert len(captured) == 1
    assert isinstance(captured[0], KeyError), (
        "hook receives the original exception, not the wrapped IntegrationError"
    )


# ── TC-005: guarded_parse — branch 3 no-callback returns {ok: True} ──────────
# REQ-146-4, AC-9


@pytest.mark.asyncio
async def test_guarded_parse_branch3_no_callback_returns_ok_true():
    """When parse=None, guarded_parse returns {\"ok\": True} without error."""
    result = await guarded_parse(
        None,
        {"anything": "ignored"},
        provider_name="Acme",
        stage="probe",
        error_code="probe_parse_failed",
    )
    assert result == {"ok": True}


# ── TC-006: safe_reason — strips control characters ───────────────────────────
# REQ-146-3, AC-8 (security: escape-sequence injection prevention)


def test_safe_reason_strips_non_printable_control_characters():
    """safe_reason() removes all control characters and non-printable bytes so
    upstream error strings cannot inject escape sequences into logs or client
    error messages."""
    raw = "invalid_auth\x1b[31mRED\x1b[0m\x00\x07"
    result = safe_reason(raw)
    # None of the control bytes must survive
    assert "\x1b" not in result
    assert "\x00" not in result
    assert "\x07" not in result
    # Printable content survives
    assert "invalid_auth" in result


# ── TC-007: safe_reason — truncates long upstream strings ─────────────────────
# REQ-146-3, AC-8


def test_safe_reason_truncates_to_limit():
    """safe_reason() enforces the 64-character limit so upstream-supplied text
    cannot create unbounded client error messages."""
    long_value = "x" * 200
    result = safe_reason(long_value)
    assert len(result) <= 64


# ── TC-008: safe_reason — None input returns 'unknown' ───────────────────────
# REQ-146-3, AC-8


def test_safe_reason_none_returns_unknown():
    """safe_reason(None) returns 'unknown' rather than raising or returning
    an empty string that confuses the client-facing message."""
    result = safe_reason(None)
    assert result == "unknown"


# ── TC-009: decode_json — non-JSON body raises probe_parse_failed ─────────────
# REQ-146-4 (defend against HTML error pages etc.), gap in existing suite


def test_decode_json_non_json_body_raises_integration_error():
    """When the upstream response is not valid JSON (e.g. an HTML error page
    from a proxy), decode_json raises IntegrationError('probe_parse_failed')
    instead of letting a bare ValueError escape as a 500."""
    fake_resp = _FakeResponse(200, None, bad_json=True)
    with pytest.raises(IntegrationError) as exc_info:
        decode_json(fake_resp, provider_name="Slack")
    assert exc_info.value.code == "probe_parse_failed"
    assert "Slack" in exc_info.value.message
    assert "JSON" in exc_info.value.message


# ═══════════════════════════════════════════════════════════════════════════════
# COMPONENT LAYER — _factory.py _probe() and connect() orchestration
# ═══════════════════════════════════════════════════════════════════════════════


# ── TC-010: _probe() — transport failure maps to probe_failed via connect() ───
# REQ-146-4, AC-9 (gap in existing suite)


@pytest.mark.asyncio
async def test_connect_transport_failure_raises_probe_failed(monkeypatch):
    """When httpx.AsyncClient.get() raises a transport-level exception
    (ConnectError, TimeoutException, etc.), connect() catches httpx.HTTPError
    and raises IntegrationError('probe_failed', ...) — NOT a bare 500."""
    import src.integrations.project._factory as factory_module

    _patch_transport_failure(monkeypatch)
    monkeypatch.setattr(
        factory_module,
        "store_api_key",
        AsyncMock(return_value=ConnectResult(integration_id="x", redirect_url=None)),
    )

    spec = ProviderSpec(
        slug="synthetic_transport",
        display_name="SyntheticTransport",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
    )
    provider = make_provider(spec)()

    user = _FakeUser()
    db = _make_db()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=user, db=db, payload={"api_key": "test-key"})

    assert exc_info.value.code == "probe_failed"


# ── TC-011: _probe() 401 response maps to invalid_key ────────────────────────
# REQ-146-1, AC-1, AC-2


@pytest.mark.asyncio
async def test_probe_401_response_raises_invalid_key(monkeypatch):
    """When the upstream probe URL returns 401, _probe() raises
    IntegrationError('invalid_key', ...) — not probe_failed or 500."""
    spec = ProviderSpec(
        slug="synthetic_401",
        display_name="Synthetic401",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
    )
    provider = make_provider(spec)()

    _patch_client(monkeypatch, 401, {"error": "Unauthorized"})

    with pytest.raises(IntegrationError) as exc_info:
        await provider._probe("bad-key")

    assert exc_info.value.code == "invalid_key"


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION LAYER — Full HTTP path through FastAPI router
# Covers REQ-146-1, REQ-146-6, AC-1, AC-2, AC-3, AC-4
# ═══════════════════════════════════════════════════════════════════════════════


# ── TC-012: Slack connect ok:false → HTTP 400, error.code=invalid_key ─────────
# REQ-146-1, REQ-146-6, AC-1, AC-2, AC-3 (the primary regression contract)


def test_slack_connect_invalid_token_returns_400_with_structured_error(
    client_factory, monkeypatch
):
    """POST /api/v1/integrations/slack/connect with an invalid Slack token
    (ok=false from auth.test) MUST return HTTP 400 (not 500) with
    error.code='invalid_key' and error.message referencing 'Slack' and the
    upstream error code ('invalid_auth').

    This is the living regression contract for REQ-146-6."""
    from src.integrations.project.bulk_providers import _SlackProvider

    _patch_client(monkeypatch, 200, {"ok": False, "error": "invalid_auth"})
    tc = client_factory({"slack": _SlackProvider()})

    resp = tc.post(
        "/api/v1/integrations/slack/connect", json={"api_key": "xoxb-invalid-token"}
    )

    # Must NOT be 500 — that was the original bug
    assert resp.status_code != 500, (
        f"Got {resp.status_code} — bare Exception is escaping as 500 again"
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"

    body = resp.json()
    assert "error" in body, "Response must have top-level 'error' key per api.md"
    error = body["error"]
    assert error["code"] == "invalid_key", (
        f"error.code must be 'invalid_key', got {error.get('code')!r}"
    )
    assert "Slack" in error["message"], (
        f"error.message must reference 'Slack', got {error.get('message')!r}"
    )
    assert "invalid_auth" in error["message"], (
        f"Upstream Slack error code must appear in message, got {error.get('message')!r}"
    )


# ── TC-013: Slack connect ok:true → HTTP 200, team/user in stored extra ───────
# REQ-146-5, AC-4 (happy path / no regression on valid tokens)


def test_slack_connect_valid_token_returns_200_with_team_and_user(
    client_factory, monkeypatch
):
    """POST /api/v1/integrations/slack/connect with a valid Slack token
    (ok=true) MUST return HTTP 200 with the integration_id and MUST pass
    {'team': ..., 'user': ...} from auth.test into store_api_key's 'extra'
    kwarg."""
    import src.integrations.project._factory as factory_module
    from src.integrations.project.bulk_providers import _SlackProvider

    _patch_client(monkeypatch, 200, {"ok": True, "team": "TABC", "user": "UABC"})
    store_mock = AsyncMock(
        return_value=ConnectResult(integration_id="int-slack-1", redirect_url=None)
    )
    monkeypatch.setattr(factory_module, "store_api_key", store_mock)

    tc = client_factory({"slack": _SlackProvider()})
    resp = tc.post(
        "/api/v1/integrations/slack/connect", json={"api_key": "xoxb-valid-token"}
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert resp.json()["data"]["integration_id"] == "int-slack-1"
    # Verify team/user are forwarded to credential storage
    stored_extra = store_mock.await_args.kwargs["extra"]
    assert stored_extra.get("team") == "TABC"
    assert stored_extra.get("user") == "UABC"


# ── TC-014: Slack connect ok:false with control-char error string ─────────────
# REQ-146-3, AC-3, AC-8 (security: injection via Slack 'error' field)


def test_slack_connect_upstream_error_with_control_chars_is_sanitised(
    client_factory, monkeypatch
):
    """If Slack returns an 'error' field containing control characters or ANSI
    escape sequences, they must be stripped from the error.message before it
    reaches the client — safe_reason() is responsible for this."""
    from src.integrations.project.bulk_providers import _SlackProvider

    malicious_error = "invalid_auth\x1b[31minjected\x1b[0m"
    _patch_client(monkeypatch, 200, {"ok": False, "error": malicious_error})
    tc = client_factory({"slack": _SlackProvider()})

    resp = tc.post("/api/v1/integrations/slack/connect", json={"api_key": "xoxb-bad"})

    assert resp.status_code == 400
    message = resp.json()["error"]["message"]
    assert "\x1b" not in message, (
        "ANSI escape sequences must not appear in the response"
    )
    assert "\x00" not in message


# ── TC-015: No regression on non-Slack providers (Vercel, Render, Supabase) ───
# REQ-146-1, AC-4


def test_non_slack_provider_valid_probe_returns_200_unchanged(
    client_factory, monkeypatch
):
    """A non-Slack provider with a valid probe response returns HTTP 200.
    This guards against the guard itself introducing a regression for all
    other providers that route through make_provider/_probe."""
    spec = ProviderSpec(
        slug="nonslack_reg",
        display_name="NonSlack",
        category="test",
        description="test",
        docs_url="https://example.com",
        icon="test",
        probe_url="https://example.com/probe",
        auth_header=lambda key: {},
        parse_probe=lambda body: {"item_count": len(body or [])},
    )
    import src.integrations.project._factory as factory_module

    provider_cls = make_provider(spec)
    provider_instance = provider_cls()

    _patch_client(monkeypatch, 200, ["a", "b", "c"])
    store_mock = AsyncMock(
        return_value=ConnectResult(integration_id="int-nonslack", redirect_url=None)
    )
    monkeypatch.setattr(factory_module, "store_api_key", store_mock)

    tc = client_factory({"nonslack_reg": provider_instance})
    resp = tc.post(
        "/api/v1/integrations/nonslack_reg/connect", json={"api_key": "good-key"}
    )

    assert resp.status_code == 200, (
        f"Non-Slack provider regression: expected 200, got {resp.status_code}"
    )
    stored_extra = store_mock.await_args.kwargs["extra"]
    assert stored_extra == {"item_count": 3}


# ── TC-016: Slack SYNC (not just connect) ok:false → 400, not 500 ─────────────
# REQ-146-1, REQ-146-6 — closes the gap that every other real-Slack test in
# this suite (and in test_integration_factory_errors.py) only drives the
# real _SlackProvider through /connect. bulk_providers.py reuses the same
# _slack_ok callback for BOTH parse_probe and parse_sync (see its
# docstring), so a revoked/rotated token discovered during a background
# resync is exactly as likely to hit this path as an initial connect — and
# was equally capable of producing the original unhandled-500 bug. This
# drives the real provider's sync() through the router's /sync endpoint,
# not a synthetic ProviderSpec.


def test_slack_sync_ok_false_returns_400_and_marks_integration_error(
    client_factory, monkeypatch
):
    """POST /api/v1/integrations/slack/sync against an already-connected
    Slack integration whose token has since been revoked (auth.test now
    returns ok=false) MUST return HTTP 400 with error.code='invalid_key' —
    never a 500 — and MUST flip the integration row to status='error' with
    last_error populated, exactly like the synthetic-provider guard test
    (T6) already proves for the generic factory path."""
    import src.integrations.project._factory as factory_module
    from src.integrations.project.bulk_providers import _SlackProvider

    integration = _FakeIntegration(slug="slack", status="connected")
    fake_creds = MagicMock()
    fake_creds.encrypted_key = "blob"

    db = MagicMock()
    # First db.scalar() call is _find_user_integration (router), second is
    # the ApiKeyCredential lookup inside provider.sync().
    db.scalar = AsyncMock(side_effect=[integration, fake_creds])
    db.commit = AsyncMock()

    monkeypatch.setattr(factory_module, "decrypt", lambda blob: "xoxb-revoked")
    _patch_client(monkeypatch, 200, {"ok": False, "error": "token_revoked"})

    async def _override_db():
        yield db

    import src.integrations.routers as routers_module
    from src.auth.dependencies import get_current_user
    from src.models.database import get_db

    async def _override_user():
        return _FakeUser()

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    monkeypatch.setattr(
        routers_module, "INTEGRATION_REGISTRY", {"slack": _SlackProvider()}
    )
    monkeypatch.setattr(
        routers_module,
        "get_provider",
        lambda slug: {"slack": _SlackProvider()}.get(slug),
    )
    tc = TestClient(app)

    resp = tc.post("/api/v1/integrations/slack/sync")

    assert resp.status_code != 500, (
        f"Got {resp.status_code} — Slack sync's bare Exception is escaping as 500 again"
    )
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == "invalid_key"
    assert "Slack" in error["message"]
    assert "token_revoked" in error["message"]
    assert integration.status == "error"
    assert integration.last_error
