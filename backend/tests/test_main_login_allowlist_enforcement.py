"""Regression tests for main.py's fail-closed AUTH_ALLOWED_EMAILS check.

FEAT-158 gate finding: the previous version of this check inferred
"production" solely from BACKEND_URL's URL scheme, with no test proving
it actually fires. These call the REAL ``src.main._enforce_login_allowlist``
under a patched environment rather than reimplementing its branch, so the
test still fails if the real guard is ever deleted or weakened.
"""

from __future__ import annotations

import pytest
from src.main import _enforce_login_allowlist


def test_render_flag_without_allowlist_raises(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_ALLOWED_EMAILS"):
        _enforce_login_allowlist()


def test_https_backend_url_without_allowlist_raises(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("BACKEND_URL", "https://arshad-ai.onrender.com")
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_ALLOWED_EMAILS"):
        _enforce_login_allowlist()


def test_production_with_blank_allowlist_raises(monkeypatch):
    """AUTH_ALLOWED_EMAILS='   ' (blank, not unset) must still raise."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "   ")
    with pytest.raises(RuntimeError, match="AUTH_ALLOWED_EMAILS"):
        _enforce_login_allowlist()


def test_production_with_allowlist_does_not_raise(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    _enforce_login_allowlist()  # must not raise


def test_non_production_without_allowlist_does_not_raise(monkeypatch):
    """Local dev (neither RENDER nor an https BACKEND_URL) never raises,
    even with AUTH_ALLOWED_EMAILS unset — this guard is early feedback,
    not the actual safety mechanism (is_email_allowed denies by default
    regardless of whether this check fires)."""
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    _enforce_login_allowlist()  # must not raise
