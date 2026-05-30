"""Tests for /api/v1/auth/* routes."""

import time

from fastapi.testclient import TestClient
from src.auth.routers import _make_signed_state, _verify_signed_state
from src.main import app

client = TestClient(app)


def test_logout_returns_204():
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert response.content == b""


def test_make_signed_state_roundtrips():
    signed = _make_signed_state("abc123")
    assert _verify_signed_state(signed)


def test_verify_signed_state_rejects_tampered_sig():
    signed = _make_signed_state("abc123")
    tampered = signed[:-4] + "0000"
    assert not _verify_signed_state(tampered)


def test_verify_signed_state_rejects_tampered_nonce():
    signed = _make_signed_state("abc123")
    parts = signed.split(".")
    parts[0] = "evil"
    assert not _verify_signed_state(".".join(parts))


def test_verify_signed_state_rejects_expired(monkeypatch):
    signed = _make_signed_state("abc123")
    future = time.time() + 400
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod.time, "time", lambda: future)
    assert not _verify_signed_state(signed)


def test_verify_signed_state_rejects_malformed():
    assert not _verify_signed_state("notvalid")
    assert not _verify_signed_state("")
    assert not _verify_signed_state("only.two")


def test_verify_signed_state_rejects_non_numeric_timestamp():
    signed = _make_signed_state("abc123")
    parts = signed.split(".", 2)
    parts[1] = "not-a-number"
    assert not _verify_signed_state(".".join(parts))


def test_verify_signed_state_rejects_empty_nonce():
    signed = _make_signed_state("abc123")
    parts = signed.split(".", 2)
    parts[0] = ""
    assert not _verify_signed_state(".".join(parts))
