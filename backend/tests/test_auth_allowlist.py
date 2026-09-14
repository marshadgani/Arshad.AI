"""Unit tests for src.auth.allowlist — the AUTH_ALLOWED_EMAILS gate (FEAT-158)."""

from __future__ import annotations

from src.auth.allowlist import allowed_emails, is_email_allowed


def test_allowed_emails_empty_when_unset(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    assert allowed_emails() == set()


def test_allowed_emails_parses_comma_separated_list(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", " Owner@Example.com , second@example.com ")
    assert allowed_emails() == {"owner@example.com", "second@example.com"}


def test_allowed_emails_ignores_empty_entries(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com,,  ,")
    assert allowed_emails() == {"owner@example.com"}


def test_is_email_allowed_permissive_when_allowlist_empty(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    assert is_email_allowed("anyone@example.com") is True


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
