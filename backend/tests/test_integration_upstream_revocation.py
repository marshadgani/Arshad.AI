"""Regression guard: disconnect() must really revoke, or really say it can't.

The bug these tests exist for: `IntegrationProvider._revoke_upstream()`
was added as an overridable hook with a no-op default, *no provider ever
overrode it*, and the disconnect confirmation dialog nonetheless told
every user their credentials were "revoked with the provider". Nothing
raised, nothing failed a test, and the gap was invisible from either side
— the backend looked like it supported revocation, the frontend looked
like it was telling the truth.

So these tests assert the two halves that were missing, plus the guard
that stops the halves drifting apart again:

  1. every registered provider *declares* what disconnect() does upstream
     (and the declaration is reachable by the frontend);
  2. a provider that claims revocation actually performs one;
  3. a provider that claims it cannot makes no upstream call at all.

They are deliberately written against the whole registry rather than a
hand-picked list: a provider added next month is covered on the day it is
added, which a per-provider test would not be.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.auth.crypto import encrypt
from src.integrations import presenters
from src.integrations.base import (
    IntegrationError,
    IntegrationProvider,
    UpstreamRevocation,
    cannot_revoke,
    revokes_via,
)
from src.integrations.personal._oauth_base import OAuthIntegrationProvider
from src.integrations.registry import INTEGRATION_REGISTRY, register

# Providers whose disconnect genuinely ends access at the third party.
# Pinned as a literal set so *losing* a revocation is a test failure:
# quietly downgrading one of these to cannot_revoke() would otherwise
# look like a passing refactor while silently weakening the product's
# security posture.
EXPECTED_REVOKING_SLUGS = {
    "coinbase",
    "discord",
    "fitbit",
    "linear",
    "oura",
    "plaid",
    "reddit",
    "slack",
    "strava",
    "upstox",
    "whoop",
    "zerodha_kite",
}


def _mock_db(token_row: MagicMock | None = None) -> MagicMock:
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=False)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.scalar = AsyncMock(return_value=token_row)
    result = MagicMock()
    result.rowcount = 1
    db.execute = AsyncMock(return_value=result)
    return db


def _mock_integration(slug: str) -> MagicMock:
    integration = MagicMock()
    integration.id = uuid.uuid4()
    integration.user_id = uuid.uuid4()
    integration.slug = slug
    integration.status = "connected"
    return integration


def _oauth_token_row() -> MagicMock:
    row = MagicMock()
    row.encrypted_access_token = encrypt("access-token-value")
    row.encrypted_refresh_token = encrypt("refresh-token-value")
    return row


# ── 1. Every provider declares, and the declaration reaches the UI ─────────


@pytest.mark.parametrize("slug", sorted(INTEGRATION_REGISTRY))
def test_every_provider_declares_upstream_revocation(slug: str) -> None:
    declaration = INTEGRATION_REGISTRY[slug].upstream_revocation
    assert isinstance(declaration, UpstreamRevocation)
    # A reason is mandatory in both directions: "cannot revoke" with no
    # explanation is indistinguishable from "nobody checked", which is
    # the state this whole feature exists to make unrepresentable.
    assert declaration.detail.strip(), f"{slug} declared an empty revocation detail"


@pytest.mark.parametrize("slug", sorted(INTEGRATION_REGISTRY))
def test_declaration_is_exposed_on_the_integration_card(slug: str) -> None:
    """The frontend cannot tell the truth about a provider it can't see.

    The disconnect dialog renders `detail` verbatim, so a descriptor that
    omits it would silently fall back to a generic claim — exactly the
    failure mode being fixed.
    """
    descriptor = presenters.provider_descriptor(INTEGRATION_REGISTRY[slug])
    assert descriptor["upstream_revocation"] == {
        "supported": INTEGRATION_REGISTRY[slug].upstream_revocation.supported,
        "detail": INTEGRATION_REGISTRY[slug].upstream_revocation.detail,
    }


def test_expected_providers_revoke_upstream() -> None:
    """Guards against silently losing revocation for a provider that has it.

    Asserted as set equality, not a subset: an unexpected *addition* is
    also worth a failing test, because it means someone declared
    revokes_via(...) and this file's list of what the product promises
    was not updated alongside it.
    """
    actual = {
        slug
        for slug, provider in INTEGRATION_REGISTRY.items()
        if provider.upstream_revocation.supported
    }
    assert actual == EXPECTED_REVOKING_SLUGS


# ── 2. A claim of revocation is backed by an actual call ───────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug",
    # plaid and slack are not OAuth providers; zerodha_kite overrides
    # _revoke_upstream wholesale because Kite's logout fits no
    # revoke_style, so none of the three route through _post_revocation.
    # Each is covered by its own test below.
    sorted(EXPECTED_REVOKING_SLUGS - {"plaid", "slack", "zerodha_kite"}),
)
async def test_oauth_providers_that_claim_revocation_call_their_endpoint(
    slug: str,
) -> None:
    """Each OAuth provider claiming revocation must issue one.

    _post_revocation is stubbed rather than the HTTP client, so the test
    proves the provider reached the point of making a request with a
    decrypted token — without asserting anything about a third party's
    wire format, which would make this a test of httpx.
    """
    provider = INTEGRATION_REGISTRY[slug]
    calls: list[tuple[str, str]] = []

    class _Recording(type(provider)):  # type: ignore[misc]
        async def _post_revocation(self, token: str, *, token_type_hint: str) -> None:
            calls.append((token, token_type_hint))

    integration = _mock_integration(slug)
    await _Recording().disconnect(
        integration=integration, db=_mock_db(_oauth_token_row())
    )

    assert calls, f"{slug} declares revokes_via(...) but made no revocation call"
    assert all(token for token, _ in calls), "revocation called with an empty token"
    assert integration.status == "disconnected"


@pytest.mark.asyncio
async def test_refresh_token_is_revoked_before_the_access_token() -> None:
    """Order matters: with every provider here that issues a refresh
    token, revoking it invalidates the grant, while revoking only the
    access token would leave a credential able to mint a new one."""
    provider = INTEGRATION_REGISTRY["fitbit"]
    calls: list[tuple[str, str]] = []

    class _Recording(type(provider)):  # type: ignore[misc]
        async def _post_revocation(self, token: str, *, token_type_hint: str) -> None:
            calls.append((token, token_type_hint))

    await _Recording().disconnect(
        integration=_mock_integration("fitbit"), db=_mock_db(_oauth_token_row())
    )

    assert [hint for _, hint in calls] == ["refresh_token", "access_token"]


@pytest.mark.asyncio
async def test_zerodha_revokes_its_session_with_both_api_key_and_token() -> None:
    """Kite's logout is a DELETE carrying api_key AND access_token in the
    query string — it matches no `revoke_style`, so it is the one
    provider whose request shape is asserted directly."""
    requests: list[tuple[str, dict[str, str]]] = []

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def delete(self, url, params=None, **kw):
            requests.append((url, params or {}))
            response = MagicMock()
            response.raise_for_status = MagicMock()
            return response

    provider = INTEGRATION_REGISTRY["zerodha_kite"]
    monkey = MagicMock(return_value=_FakeClient())
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ZERODHA_KITE_CLIENT_ID", "kite-api-key")
        mp.setattr("src.integrations.personal.zerodha_kite.httpx.AsyncClient", monkey)
        await provider.disconnect(
            integration=_mock_integration("zerodha_kite"),
            db=_mock_db(_oauth_token_row()),
        )

    assert len(requests) == 1
    url, params = requests[0]
    assert url == "https://api.kite.trade/session/token"
    assert params["api_key"] == "kite-api-key"
    assert params["access_token"] == "access-token-value"


@pytest.mark.asyncio
async def test_plaid_removes_the_item_before_the_token_is_deleted() -> None:
    """Plaid is the highest-stakes revocation here: an Item left in place
    keeps the user's bank linked *and* keeps billing, so deleting only our
    encrypted copy would be the most misleading "disconnect" of all."""
    removed: list[str] = []

    async def _fake_remove_item(access_token: str) -> None:
        removed.append(access_token)

    provider = INTEGRATION_REGISTRY["plaid"]
    credential = MagicMock()
    credential.encrypted_key = encrypt("access-sandbox-abc")

    db = _mock_db(credential)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.integrations.personal.plaid_client.remove_item", _fake_remove_item
        )
        await provider.disconnect(integration=_mock_integration("plaid"), db=db)

    assert removed == ["access-sandbox-abc"]


@pytest.mark.asyncio
async def test_slack_revokes_its_token_and_checks_the_revoked_flag() -> None:
    """Slack answers `ok: false` with HTTP 200, so a 2xx proves nothing —
    only `revoked: true` does. A response without it must raise, so the
    failure is logged rather than silently counted as a revocation."""
    from src.integrations.project.bulk_providers import _slack_auth_revoke

    def _response(payload: dict[str, object]) -> MagicMock:
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value=payload)
        return response

    posted: list[dict[str, str]] = []

    class _FakeClient:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, **kw):
            posted.append({"url": url, **(headers or {})})
            return _response(self._payload)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.integrations.project.bulk_providers.httpx.AsyncClient",
            lambda **kw: _FakeClient({"ok": True, "revoked": True}),
        )
        await _slack_auth_revoke("xoxp-token")
    assert posted[0]["url"] == "https://slack.com/api/auth.revoke"
    assert posted[0]["Authorization"] == "Bearer xoxp-token"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.integrations.project.bulk_providers.httpx.AsyncClient",
            lambda **kw: _FakeClient({"ok": False, "error": "invalid_auth"}),
        )
        with pytest.raises(Exception, match="did not revoke"):
            await _slack_auth_revoke("xoxp-token")


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["strava", "oura"])
async def test_failed_revocation_never_logs_the_token(
    slug: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The `query_token` styles put the access token in the request URL,
    and httpx puts the full URL in its exception messages — which
    disconnect() logs with exc_info=True. Without deliberate handling
    that writes a live OAuth token into the application log in cleartext,
    one line before the token is deleted.

    Asserted against the *rendered* log output including tracebacks,
    because that is what actually reaches the log aggregator; checking
    only `record.getMessage()` would miss the exc_info chain entirely.

    The stub returns a real 500 `httpx.Response` rather than a
    pre-built exception, so it is the *production* `raise_for_status()`
    call that composes the message. An exception constructed here would
    carry whatever text the test chose and would pass even if the
    credential-safe handling were deleted — verified by mutation: removing
    the `from None` handler must fail this test.
    """
    import logging

    class _Failing(type(INTEGRATION_REGISTRY[slug])):  # type: ignore[misc]
        async def _send_revocation(self, client, url, token, token_type_hint):
            # The URL the real query_token style would build, token and all.
            request = httpx.Request("POST", f"{url}?access_token={token}")
            return httpx.Response(500, request=request)

    with caplog.at_level(logging.DEBUG):
        await _Failing().disconnect(
            integration=_mock_integration(slug), db=_mock_db(_oauth_token_row())
        )

    formatter = logging.Formatter()
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert "access-token-value" not in rendered, (
        f"{slug}: a live OAuth token reached the logs via the revocation failure path"
    )
    assert "refresh-token-value" not in rendered
    # The failure must still be observable — silencing it would trade one
    # bug for another.
    assert "revocation failed" in rendered.lower()


# ── 3. A provider that cannot revoke makes no upstream call ────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug",
    sorted(
        s
        for s, p in INTEGRATION_REGISTRY.items()
        if not p.upstream_revocation.supported
        and isinstance(p, OAuthIntegrationProvider)
    ),
)
async def test_providers_that_cannot_revoke_make_no_upstream_call(slug: str) -> None:
    """Not merely "doesn't crash" — must not touch the token at all.

    The Google and GitHub thin views are the reason this is asserted and
    not assumed: their tokens are the shared login grant (BR-005), and a
    revocation call for "disconnect Google Calendar" would sign the user
    out of Arshad.AI and every other Google integration at once.
    """
    db = _mock_db(_oauth_token_row())
    await INTEGRATION_REGISTRY[slug].disconnect(
        integration=_mock_integration(slug), db=db
    )
    assert db.scalar.await_count == 0, (
        f"{slug} declares it cannot revoke upstream but still read its OAuth "
        "token — the only reason to read it on this path is to present it to "
        "the provider."
    )


# ── 4. The guard that keeps declaration and implementation in step ─────────


def _concrete(**attrs: object) -> type[IntegrationProvider]:
    body: dict[str, object] = {
        "kind": "personal_oauth",
        "display_name": "T",
        "category": "test",
        "description": "test",
        "connect": lambda self, **kw: None,
        "sync": lambda self, **kw: None,
        "status": lambda self, **kw: None,
        **attrs,
    }
    return type("_TestProvider", (IntegrationProvider,), body)


def test_register_rejects_a_provider_with_no_declaration() -> None:
    with pytest.raises(RuntimeError, match="does not declare"):
        register(_concrete(slug="_undeclared"))
    assert "_undeclared" not in INTEGRATION_REGISTRY


def test_register_rejects_a_revocation_claim_with_no_implementation() -> None:
    """The original bug, reproduced as a unit test.

    A provider that says it revokes upstream but inherits the base no-op
    is precisely what shipped; registration must now refuse it.
    """
    with pytest.raises(RuntimeError, match="no way to do it"):
        register(
            _concrete(slug="_liar", upstream_revocation=revokes_via("POST /revoke"))
        )
    assert "_liar" not in INTEGRATION_REGISTRY


def test_register_rejects_an_oauth_claim_without_a_revoke_url() -> None:
    """OAuth providers inherit a *generic* _revoke_upstream that no-ops
    without a revoke_url, so "overrides the hook" is not enough evidence
    for them."""

    class _OAuthLiar(OAuthIntegrationProvider):
        slug = "_oauth_liar"
        display_name = "T"
        category = "test"
        description = "test"
        auth_url = ""
        token_url = ""
        scopes: list[str] = []
        client_id_env = "X"
        client_secret_env = "Y"
        upstream_revocation = revokes_via("POST /revoke")

        async def sync(self, *, integration, db): ...  # type: ignore[override]

    with pytest.raises(RuntimeError, match="no way to do it"):
        register(_OAuthLiar)
    assert "_oauth_liar" not in INTEGRATION_REGISTRY


def test_register_accepts_an_honest_cannot_revoke_declaration() -> None:
    cls = _concrete(
        slug="_honest", upstream_revocation=cannot_revoke("No revoke endpoint.")
    )
    try:
        register(cls)
        assert INTEGRATION_REGISTRY["_honest"].upstream_revocation.supported is False
    finally:
        INTEGRATION_REGISTRY.pop("_honest", None)


@pytest.mark.asyncio
async def test_access_token_is_revoked_even_when_the_refresh_call_fails() -> None:
    """A rejected refresh-token revocation must not skip the access token.

    Strava and Oura use the `query_token` style, whose endpoint only
    understands an *access* token — presenting the refresh token first is
    rejected. When that rejection aborted the sequence, the access token
    stayed live at the provider while the local copy was deleted and the
    dialog had already promised "revoked with the provider".
    """
    provider = INTEGRATION_REGISTRY["strava"]
    calls: list[str] = []

    class _FirstCallRejected(type(provider)):  # type: ignore[misc]
        async def _post_revocation(self, token: str, *, token_type_hint: str) -> None:
            calls.append(token_type_hint)
            if token_type_hint == "refresh_token":
                raise IntegrationError("revoke_failed", "Strava rejected it.")

    integration = _mock_integration("strava")
    await _FirstCallRejected().disconnect(
        integration=integration, db=_mock_db(_oauth_token_row())
    )

    assert calls == ["refresh_token", "access_token"]
    # disconnect() still completes: the local copy goes regardless.
    assert integration.status == "disconnected"


@pytest.mark.asyncio
async def test_a_failed_revocation_is_still_reported_to_disconnect() -> None:
    """Attempting both must not turn a failure into a silent success —
    disconnect() logs the failure, so it has to be able to see it."""
    provider = INTEGRATION_REGISTRY["fitbit"]

    class _AllRejected(type(provider)):  # type: ignore[misc]
        async def _post_revocation(self, token: str, *, token_type_hint: str) -> None:
            raise IntegrationError("revoke_failed", "Fitbit rejected it.")

    with pytest.raises(IntegrationError):
        await _AllRejected()._revoke_upstream(
            integration=_mock_integration("fitbit"), db=_mock_db(_oauth_token_row())
        )
