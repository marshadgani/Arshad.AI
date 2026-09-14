"""Pure markdown, path and frontmatter primitives for exported notes.

No DB, no HTTP, no knowledge of Arshad.AI's domains or row shapes — these
take strings and datetimes and give back strings, so a change to the
vault's path scheme or frontmatter encoding is a one-file change.

Frontmatter scalars are JSON-encoded (json.dumps) so they are always
single-line and safe for the hand-rolled YAML parser in
services/ingestion/obsidian.py._parse_frontmatter. The parser doesn't
strip quotes from scalar values, so fm["domain"] == '"calendar"' in
tests — intentional, documented in tests/test_obsidian_export_renderers.py.
Exported notes are excluded from re-ingestion via the EXPORT_ROOT prefix
skip in services/ingestion/obsidian.py, so this quirk is harmless in prod.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .config import EXPORT_ROOT

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]")
_MULTI_DASH_RE = re.compile(r"-{2,}")
_MAX_SEGMENT_BASE = 71  # 71 + 1 dash + 8 hash chars = 80 total


def safe_segment(s: str, id_suffix: str) -> str:
    """Sanitise a user-derived string to a vault-path-safe slug.

    Appends an 8-char sha256 prefix of id_suffix for collision resistance:
    two rows with identical base strings (e.g. same event title) but
    different IDs never share a vault path. Max total length 80 chars
    (71 base + 1 dash + 8 hash = 80).
    """
    hash_part = hashlib.sha256(id_suffix.encode("utf-8")).hexdigest()[:8]
    cleaned = _UNSAFE_RE.sub("-", s)
    cleaned = _MULTI_DASH_RE.sub("-", cleaned).strip("-")
    if not cleaned:
        cleaned = "note"
    cleaned = cleaned[:_MAX_SEGMENT_BASE]
    return f"{cleaned}-{hash_part}"


def escape_wikilinks(s: str) -> str:
    """Prevent user-derived strings from minting Obsidian [[wikilinks]].

    Replaces [[ with \\[\\[ and ]] with \\]\\] so that inbound PR titles,
    email subjects, or any user-controlled string cannot create vault
    links — enforcing the FEAT-141 non-reintroduction boundary in code.
    """
    return s.replace("[[", r"\[\[").replace("]]", r"\]\]")


def date_parts(dt: Any) -> tuple[str, str, str]:
    """Return (date_str, year, month) for a datetime, or ('', '', '').

    Takes the datetime rather than the row so this layer stays free of
    any assumption about what an ingested row looks like.
    """
    if not isinstance(dt, datetime):
        return "", "", ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y"), dt.strftime("%m")


def vault_path(folder: str, date_str: str, year: str, month: str, slug: str) -> str:
    """Build the canonical export path: EXPORT_ROOT/<Folder>/YYYY/MM/<file>.md"""
    filename = f"{date_str}-{slug}.md" if date_str else f"{slug}.md"
    return f"{EXPORT_ROOT}{folder}/{year}/{month}/{filename}"


def frontmatter_block(fields: dict[str, Any]) -> str:
    """Render fields as a YAML frontmatter block — lists become inline
    arrays, everything else a JSON-encoded scalar (see module docstring)."""
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            encoded = "[" + ", ".join(json.dumps(item) for item in value) + "]"
        else:
            encoded = json.dumps(value)
        lines.append(f"{key}: {encoded}")
    lines.append("---")
    return "\n".join(lines)


def assemble(frontmatter: dict[str, Any], body_lines: list[str]) -> str:
    """Join a frontmatter block and body into a complete note."""
    return frontmatter_block(frontmatter) + "\n\n" + "\n".join(body_lines) + "\n"


__all__ = [
    "assemble",
    "date_parts",
    "escape_wikilinks",
    "frontmatter_block",
    "safe_segment",
    "vault_path",
]
