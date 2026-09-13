"""Person identity derivation — the one place this logic lives.

Every extractor that references a person (calendar attendee, GitHub
actor) calls these helpers so the same real-world person always yields
the same ``stable_entity_id``, without needing the resolver to do any
fuzzy matching. Email-only identity; no name-based merging in v1 — a
wrong merge is unrecoverable from the vault side.
"""

from __future__ import annotations

import hashlib

_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if domain in _GMAIL_DOMAINS:
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"


def person_id_from_email(email: str) -> str:
    normalized = normalize_email(email)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"person:{digest}"


def person_id_from_github_login(login: str) -> str:
    return f"person:gh:{login.strip().lower()}"
