"""Vault path policy — the single place that decides where a note lives.

Splitting this out of ``resolve.py`` means "how is an entity named and
filed in the vault" is answerable without reading identity-resolution,
DB-upsert, or sweep logic, and is testable with no session at all. It
also gives ``render.py`` a legitimate import for ``ONTOLOGY_VAULT_ROOT``
instead of re-hardcoding "Arshad.AI" inside its Dataview queries.
"""

from __future__ import annotations

import re

ONTOLOGY_VAULT_ROOT = "Arshad.AI"

_ENTITY_FOLDER = {
    "Person": "People",
    "Event": "Calendar",
    "Thread": "Email",
    "Repo": "GitHub/Repos",
    "IssuePR": "GitHub/Issues",
    "MOC": "MOCs",
}
_FALLBACK_FOLDER = "Misc"

# Filenames are derived from untrusted display names (Gmail subjects,
# calendar titles set by the inviter). Beyond the characters git/OS
# refuse, this also drops the ones that are dangerous *inside a vault*:
# "[" "]" "|" "#" "^" are wikilink syntax, so leaving them in a filename
# produces links that either dangle or resolve to the wrong note, and
# "<" ">" would carry raw HTML into every link alias rendering the name.
_INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|\[\]#^~\x00-\x1f\x7f]')
# A leading "." (or "-", which reads as a flag to some tooling) is
# stripped so an attacker-chosen title can never produce a dotfile such
# as ".gitignore.md" inside the managed folders.
_LEADING_JUNK_RE = re.compile(r"^[.\-\s]+")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_FILENAME_LEN = 120


def slugify_filename(name: str) -> str:
    cleaned = _INVALID_CHARS_RE.sub("", name)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    cleaned = _LEADING_JUNK_RE.sub("", cleaned).strip()
    return cleaned[:_MAX_FILENAME_LEN].strip() or "untitled"


def note_path(entity_type: str, display_name: str) -> str:
    """The path an entity WANTS, before collision handling."""
    folder = _ENTITY_FOLDER.get(entity_type, _FALLBACK_FOLDER)
    return f"{ONTOLOGY_VAULT_ROOT}/{folder}/{slugify_filename(display_name)}.md"


def resolve_collision(desired_path: str, taken: set[str]) -> str:
    """First free ``<stem> (n).md`` if ``desired_path`` is already claimed."""
    if desired_path not in taken:
        return desired_path
    stem, _, ext = desired_path.rpartition(".")
    n = 2
    while True:
        candidate = f"{stem} ({n}).{ext}"
        if candidate not in taken:
            return candidate
        n += 1


def note_target(vault_path: str) -> str:
    """The link target Obsidian actually resolves: the note's basename
    without the ``.md`` extension."""
    basename = vault_path.rsplit("/", 1)[-1]
    return basename[:-3] if basename.endswith(".md") else basename
