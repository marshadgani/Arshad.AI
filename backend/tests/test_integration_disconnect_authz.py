"""FEAT-145 gap: integrations/authz.py's project_disconnect_decision() had
zero test coverage anywhere in the suite, despite being the sole gate that
stops a non-admin user from deleting a shared project_apikey credential
(Render, Vercel, Supabase, Plaid's own project variant, etc.) now that
disconnect() genuinely destroys rows instead of only flipping a status
flag. This is exactly the kind of authorization logic that must be pinned:
a silent regression here turns "any authenticated user" back into an
acceptable audience for deleting shared infrastructure credentials.

Also covers the router-level integration: the 403 path in
_find_user_integration_for_disconnect, and that a denied disconnect leaves
the credential row untouched (no partial side effect before the 403).
"""

from __future__ import annotations

import logging
import uuid

from src.integrations.authz import (
    ADMIN_EMAILS_ENV,
    ADMIN_USER_IDS_ENV,
    project_disconnect_decision,
)

# ── project_disconnect_decision — pure policy ───────────────────────────────


def test_admin_user_id_allowed(monkeypatch):
    admin_id = uuid.uuid4()
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, str(admin_id))
    monkeypatch.setenv(ADMIN_EMAILS_ENV, "")

    decision = project_disconnect_decision(
        slug="render", user_id=admin_id, email="anyone@example.com"
    )

    assert decision == "allowed"


def test_admin_email_allowed(monkeypatch):
    monkeypatch.setenv(ADMIN_EMAILS_ENV, "admin@example.com")
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, "")

    decision = project_disconnect_decision(
        slug="render", user_id=uuid.uuid4(), email="admin@example.com"
    )

    assert decision == "allowed"


def test_admin_email_comparison_is_case_insensitive(monkeypatch):
    monkeypatch.setenv(ADMIN_EMAILS_ENV, "Admin@Example.COM")
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, "")

    decision = project_disconnect_decision(
        slug="render", user_id=uuid.uuid4(), email="admin@example.com"
    )

    assert decision == "allowed"


def test_non_admin_denied_when_admins_configured(monkeypatch):
    monkeypatch.setenv(ADMIN_EMAILS_ENV, "admin@example.com")
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, "")

    decision = project_disconnect_decision(
        slug="render", user_id=uuid.uuid4(), email="notanadmin@example.com"
    )

    assert decision == "denied"


def test_non_admin_denied_even_with_no_email(monkeypatch):
    """A user with email=None (e.g. an OAuth account without a verified
    email) must not accidentally match an empty ADMIN_EMAILS entry."""
    monkeypatch.setenv(ADMIN_EMAILS_ENV, "admin@example.com")
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, "")

    decision = project_disconnect_decision(
        slug="render", user_id=uuid.uuid4(), email=None
    )

    assert decision == "denied"


def test_unguarded_when_both_env_vars_unset(monkeypatch, caplog):
    """Fail-open default, but must be logged loudly (per DECISION.md) —
    never a silent bypass."""
    monkeypatch.setenv(ADMIN_EMAILS_ENV, "")
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, "")

    with caplog.at_level(logging.WARNING):
        decision = project_disconnect_decision(
            slug="render", user_id=uuid.uuid4(), email="anyone@example.com"
        )

    assert decision == "unguarded"
    assert any(
        "unguarded" in rec.message.lower() and rec.levelno >= logging.WARNING
        for rec in caplog.records
    )


def test_whitespace_and_blank_entries_in_csv_env_are_ignored(monkeypatch):
    monkeypatch.setenv(ADMIN_EMAILS_ENV, " , admin@example.com ,,")
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, "")

    decision = project_disconnect_decision(
        slug="render", user_id=uuid.uuid4(), email="admin@example.com"
    )

    assert decision == "allowed"


def test_user_id_matched_as_string_not_uuid_identity(monkeypatch):
    """user_id may arrive as a str (e.g. from a JWT claim) rather than a
    uuid.UUID instance — the comparison must still work."""
    admin_id = uuid.uuid4()
    monkeypatch.setenv(ADMIN_USER_IDS_ENV, str(admin_id))
    monkeypatch.setenv(ADMIN_EMAILS_ENV, "")

    decision = project_disconnect_decision(
        slug="render", user_id=str(admin_id), email=None
    )

    assert decision == "allowed"
