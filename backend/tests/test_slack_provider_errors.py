"""Slack replies HTTP 200 with ok:false for a bad token; that must surface as a
clean IntegrationError (a 4xx), never a bare Exception (a 500)."""

import pytest
from src.integrations.base import IntegrationError
from src.integrations.project import bulk_providers as bp


def test_probe_returns_identity_for_a_valid_token():
    body = {"ok": True, "team": "Acme", "user": "arshad", "url": "x"}
    assert bp._slack_parse_probe(body) == {"team": "Acme", "user": "arshad"}


@pytest.mark.parametrize("body", [{"ok": False, "error": "invalid_auth"}, {}, None])
def test_probe_rejects_a_bad_token_with_integration_error(body):
    with pytest.raises(IntegrationError) as exc:
        bp._slack_parse_probe(body)
    assert exc.value.code == "invalid_key"


def test_probe_error_names_slacks_reason_without_the_token():
    with pytest.raises(IntegrationError) as exc:
        bp._slack_parse_probe({"ok": False, "error": "token_revoked"})
    assert "token_revoked" in exc.value.message


def test_sync_rejects_ok_false_instead_of_storing_empty_identity():
    with pytest.raises(IntegrationError) as exc:
        bp._slack_parse_sync({"ok": False, "error": "account_inactive"})
    assert exc.value.code == "sync_failed"


def test_sync_returns_identity_when_ok():
    assert bp._slack_parse_sync({"ok": True, "team": "T", "user": "u"}) == {
        "team": "T",
        "user": "u",
    }


def test_connect_with_a_rejected_token_raises_a_clean_error_end_to_end(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import httpx
    from src.integrations.project import _factory
    from src.integrations.registry import get_provider

    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"ok": False, "error": "invalid_auth"}
            )
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(_factory.httpx, "AsyncClient", client)
    provider = get_provider("slack")

    async def go():
        await provider.connect(
            user=SimpleNamespace(id="u1"), db=None, payload={"api_key": "xoxp-bad"}
        )

    with pytest.raises(IntegrationError) as exc:
        asyncio.run(go())
    assert exc.value.code == "invalid_key"
    assert "xoxp-bad" not in exc.value.message
