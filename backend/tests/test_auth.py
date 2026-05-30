"""Tests for /api/v1/auth/* routes."""

import time

from fastapi.testclient import TestClient
from src.auth.routers import _make_state_cookie, _verify_state_cookie
from src.main import app

client = TestClient(app)

SECRET = "test-secret-key-for-unit-tests-only-32chars-x"


def test_logout_returns_204():
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert response.content == b""


def test_make_state_cookie_roundtrips():
    cookie = _make_state_cookie("abc123", "google")
    assert _verify_state_cookie(cookie, "abc123", "google")


def test_verify_state_cookie_rejects_wrong_state():
    cookie = _make_state_cookie("abc123", "google")
    assert not _verify_state_cookie(cookie, "wrong", "google")


def test_verify_state_cookie_rejects_wrong_provider():
    cookie = _make_state_cookie("abc123", "google")
    assert not _verify_state_cookie(cookie, "abc123", "github")


def test_verify_state_cookie_rejects_tampered_sig():
    cookie = _make_state_cookie("abc123", "google")
    tampered = cookie[:-4] + "0000"
    assert not _verify_state_cookie(tampered, "abc123", "google")


def test_verify_state_cookie_rejects_expired(monkeypatch):
    cookie = _make_state_cookie("abc123", "google")
    # Patch time.time in the routers module so _verify_state_cookie sees the future
    future = time.time() + 400
    import src.auth.routers as routers_mod

    monkeypatch.setattr(routers_mod.time, "time", lambda: future)
    assert not _verify_state_cookie(cookie, "abc123", "google")


def test_verify_state_cookie_rejects_malformed():
    assert not _verify_state_cookie("notavalidcookie", "abc123", "google")
    assert not _verify_state_cookie("", "abc123", "google")
