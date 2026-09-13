"""Unit tests — identity derivation (pure functions, zero I/O).

Covers:
- normalize_email: lowercase, whitespace strip, gmail dot/plus normalization
- person_id_from_email: stable sha256-prefix stable_entity_id
- person_id_from_github_login: person:gh:{login} format
All assertions are deterministic; no DB/network required.
"""

from __future__ import annotations

from src.services.ingestion.ontology.identity import (
    normalize_email,
    person_id_from_email,
    person_id_from_github_login,
)


# ── TC-001 ─────────────────────────────────────────────────────────
class TestNormalizeEmail:
    def test_lowercases(self):
        assert normalize_email("Alice@GMAIL.COM") == "alice@gmail.com"

    def test_strips_whitespace(self):
        assert normalize_email("  bob@example.com  ") == "bob@example.com"

    def test_strips_gmail_plus_variant(self):
        assert normalize_email("john.doe+work@gmail.com") == "johndoe@gmail.com"

    def test_strips_gmail_dots(self):
        assert normalize_email("j.o.h.n@gmail.com") == "john@gmail.com"

    def test_gmail_dot_and_plus_combined(self):
        # john.doe+work@gmail.com == johndoe@gmail.com
        result = normalize_email("john.doe+work@gmail.com")
        assert result == "johndoe@gmail.com"

    def test_googlemail_treated_as_gmail(self):
        assert normalize_email("j.d+tag@googlemail.com") == "jd@googlemail.com"

    def test_non_gmail_preserves_dots(self):
        # non-gmail: dots are significant
        result = normalize_email("first.last@example.com")
        assert result == "first.last@example.com"

    def test_non_gmail_preserves_plus(self):
        result = normalize_email("user+tag@outlook.com")
        assert result == "user+tag@outlook.com"

    def test_empty_string_returns_empty(self):
        assert normalize_email("") == ""

    def test_no_at_sign_returns_input_lowercased(self):
        # Edge: no @ — returns lowercased input, no crash
        assert normalize_email("notanemail") == "notanemail"


# ── TC-002 ─────────────────────────────────────────────────────────
class TestPersonIdFromEmail:
    def test_format_starts_with_person_prefix(self):
        pid = person_id_from_email("alice@example.com")
        assert pid.startswith("person:")

    def test_16_hex_char_digest(self):
        pid = person_id_from_email("alice@example.com")
        digest_part = pid[len("person:") :]
        assert len(digest_part) == 16
        assert all(c in "0123456789abcdef" for c in digest_part)

    def test_stable_across_calls(self):
        assert person_id_from_email("bob@example.com") == person_id_from_email(
            "bob@example.com"
        )

    def test_gmail_variants_produce_same_id(self):
        # john.doe+work@gmail.com normalizes to johndoe@gmail.com → same id
        assert person_id_from_email("john.doe+work@gmail.com") == person_id_from_email(
            "johndoe@gmail.com"
        )

    def test_different_emails_produce_different_ids(self):
        assert person_id_from_email("alice@example.com") != person_id_from_email(
            "bob@example.com"
        )

    def test_case_insensitive(self):
        assert person_id_from_email("Alice@EXAMPLE.COM") == person_id_from_email(
            "alice@example.com"
        )


# ── TC-003 ─────────────────────────────────────────────────────────
class TestPersonIdFromGithubLogin:
    def test_format(self):
        pid = person_id_from_github_login("octocat")
        assert pid == "person:gh:octocat"

    def test_lowercases_login(self):
        assert person_id_from_github_login("OctoCat") == "person:gh:octocat"

    def test_strips_whitespace(self):
        assert person_id_from_github_login("  octocat  ") == "person:gh:octocat"

    def test_differs_from_email_id(self):
        # A github-only actor has a different id format than an email-based person
        email_id = person_id_from_email("octocat@example.com")
        github_id = person_id_from_github_login("octocat")
        assert email_id != github_id
