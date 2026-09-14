"""Unit tests for src.auth.allowlist — the AUTH_ALLOWED_EMAILS gate (FEAT-158)."""

from __future__ import annotations

from src.auth.allowlist import (
    allowed_emails,
    is_email_allowed,
    is_local_dev_open_login,
    is_production_backend,
)


def _unset_allowlist_env(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("AUTH_ALLOW_ALL_LOGINS", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("BACKEND_URL", raising=False)


def test_allowed_emails_empty_when_unset(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    assert allowed_emails() == set()


def test_allowed_emails_parses_comma_separated_list(monkeypatch):
    monkeypatch.setenv(
        "AUTH_ALLOWED_EMAILS", " Owner@Example.com , second@example.com "
    )
    assert allowed_emails() == {"owner@example.com", "second@example.com"}


def test_allowed_emails_ignores_empty_entries(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com,,  ,")
    assert allowed_emails() == {"owner@example.com"}


# ── deny-by-default ─────────────────────────────────────────────────────────


def test_is_email_allowed_denies_everyone_when_allowlist_empty_and_no_opt_in(
    monkeypatch,
):
    _unset_allowlist_env(monkeypatch)
    assert is_email_allowed("anyone@example.com") is False


def test_is_email_allowed_permissive_with_explicit_local_dev_opt_in(monkeypatch):
    _unset_allowlist_env(monkeypatch)
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    assert is_email_allowed("anyone@example.com") is True


def test_is_email_allowed_ignores_opt_in_once_allowlist_is_set(monkeypatch):
    """AUTH_ALLOW_ALL_LOGINS is only read when the allowlist is empty."""
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    assert is_email_allowed("attacker@example.com") is False


def test_is_email_allowed_none_or_empty_email_denied(monkeypatch):
    _unset_allowlist_env(monkeypatch)
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    assert is_email_allowed(None) is False
    assert is_email_allowed("") is False


def test_is_local_dev_open_login_accepts_common_truthy_spellings(monkeypatch):
    for value in ("1", "true", "True", "yes", "YES"):
        monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", value)
        assert is_local_dev_open_login() is True


def test_is_local_dev_open_login_false_when_unset(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOW_ALL_LOGINS", raising=False)
    assert is_local_dev_open_login() is False


# ── allowlist membership ────────────────────────────────────────────────────


def test_is_email_allowed_true_for_listed_email(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    assert is_email_allowed("owner@example.com") is True


def test_is_email_allowed_case_insensitive(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "Owner@Example.com")
    assert is_email_allowed("owner@example.com") is True
    assert is_email_allowed("OWNER@EXAMPLE.COM") is True


def test_is_email_allowed_false_for_unlisted_email(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    assert is_email_allowed("attacker@example.com") is False


def test_is_email_allowed_strips_whitespace_on_input(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    assert is_email_allowed("  owner@example.com  ") is True


# ── is_production_backend ───────────────────────────────────────────────────


def test_is_production_backend_false_when_neither_signal_set(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("BACKEND_URL", raising=False)
    assert is_production_backend() is False


def test_is_production_backend_true_when_render_flag_set(monkeypatch):
    """RENDER is Render's own guaranteed signal — independent of BACKEND_URL,
    so a misconfigured/unset BACKEND_URL can't silently defeat this."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("BACKEND_URL", raising=False)
    assert is_production_backend() is True


def test_is_production_backend_true_when_backend_url_is_https(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("BACKEND_URL", "https://arshad-ai.onrender.com")
    assert is_production_backend() is True


def test_is_production_backend_false_for_http_backend_url_without_render(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    assert is_production_backend() is False
