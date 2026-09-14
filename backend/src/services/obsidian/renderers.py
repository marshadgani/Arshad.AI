"""Per-domain note renderers: ingested row -> RenderedNote.

Pure functions: no DB, no HTTP. Each renderer takes an ingested row (or
any object with .raw, .occurred_at, .provider_id, .id attributes) and
returns a RenderedNote(path, content, frontmatter). The shared
slug/path/frontmatter/body machinery lives in markdown.py; only what
differs between calendar, email and GitHub is here.

FEAT-141 non-reintroduction boundary enforced in code:
- escape_wikilinks() neutralises [[ and ]] in every user-derived string
  before it reaches rendered output — no inbound PR title or email subject
  can mint an Obsidian vault link.
- No ontology, no MOC, no entity-graph — flat per-domain markdown only.
- Email notes: subject + capped snippet only, never full bodies.
- Email addresses never in frontmatter tags; in body only when
  ExportConfig.include_addresses is True.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import ExportConfig
from .markdown import (
    assemble,
    date_parts,
    escape_wikilinks,
    safe_segment,
    vault_path,
)

_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


@dataclass
class RenderedNote:
    """Result of a single renderer call."""

    path: str
    content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)


def _compose(
    *,
    folder: str,
    domain: str,
    title: str,
    date_str: str,
    year: str,
    month: str,
    slug: str,
    tags: list[str],
    body_lines: list[str],
    extra_frontmatter: dict[str, Any] | None = None,
) -> RenderedNote:
    """Assemble the parts every domain note shares.

    ``extra_frontmatter`` is inserted after ``source`` and before ``tags``
    so the emitted key order stays byte-identical per domain.
    """
    frontmatter: dict[str, Any] = {
        "title": title,
        "date": date_str,
        "domain": domain,
        "source": "arshad-ai",
        **(extra_frontmatter or {}),
        "tags": tags,
    }
    return RenderedNote(
        path=vault_path(folder, date_str, year, month, slug),
        content=assemble(frontmatter, [f"## {title}", "", *body_lines]),
        frontmatter=frontmatter,
    )


def render_calendar_note(row: Any, cfg: ExportConfig | None = None) -> RenderedNote:
    """Render an IngestedCalendarEvent row as a vault markdown note."""
    raw: dict[str, Any] = getattr(row, "raw", {}) or {}
    date_str, year, month = date_parts(getattr(row, "occurred_at", None))
    provider_id = str(getattr(row, "provider_id", "") or "")

    summary_raw = str(raw.get("summary") or "Untitled Event")
    start_time = str(raw.get("start") or raw.get("start_time") or date_str or "")
    end_time = str(raw.get("end") or raw.get("end_time") or "")
    location_raw = str(raw.get("location") or "")
    description_raw = str(raw.get("description") or "")

    body: list[str] = []
    if start_time:
        body.append(f"**Start:** {escape_wikilinks(start_time)}")
    if end_time:
        body.append(f"**End:** {escape_wikilinks(end_time)}")
    if location_raw:
        body.append(f"**Location:** {escape_wikilinks(location_raw)}")
    if description_raw:
        body.extend(["", escape_wikilinks(description_raw)])

    return _compose(
        folder="Calendar",
        domain="calendar",
        title=escape_wikilinks(summary_raw),
        date_str=date_str,
        year=year,
        month=month,
        slug=safe_segment(summary_raw, provider_id),
        tags=["calendar", "arshad-ai"],
        body_lines=body,
    )


def _split_participants(raw: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Separate display names from raw email addresses.

    Addresses are excluded from frontmatter tags regardless of the
    include_addresses setting; only the caller decides whether the
    address list reaches the body.

    Detection uses re.search, not re.match: ``participants`` is
    provider-shaped and routinely carries the RFC 5322 display form
    ``"Bob Smith <bob@example.com>"``, where the address is not at
    offset 0. re.match anchors at the start and would classify those
    entries as display names, leaking the address into
    frontmatter['tags'] — the exact PII escape this function exists to
    prevent. re.search also fails safe for any entry that merely
    *contains* an address (e.g. a str()'d provider dict).
    """
    display_names: list[str] = []
    addresses: list[str] = []
    for entry in list(raw.get("participants") or []) + list(raw.get("from") or []):
        s = str(entry)
        if _ADDRESS_RE.search(s):
            addresses.append(s)
        else:
            display_names.append(s)
    return display_names, addresses


def render_email_note(row: Any, cfg: ExportConfig | None = None) -> RenderedNote:
    """Render an IngestedGmailThread row as a vault markdown note.

    PII controls:
    - snippet capped at cfg.snippet_max_chars (default 500).
    - Raw email addresses never appear in frontmatter tags.
    - Addresses appear in the note body only when cfg.include_addresses
      is True (opt-in via OBSIDIAN_EXPORT_INCLUDE_ADDRESSES env var).
    - No full email bodies — subject + snippet only.
    """
    if cfg is None:
        cfg = ExportConfig()
    raw: dict[str, Any] = getattr(row, "raw", {}) or {}
    date_str, year, month = date_parts(getattr(row, "occurred_at", None))
    provider_id = str(getattr(row, "provider_id", "") or "")

    subject_raw = str(raw.get("subject") or "No Subject")
    snippet_raw = str(raw.get("snippet") or raw.get("body") or "")
    snippet = escape_wikilinks(snippet_raw[: cfg.snippet_max_chars])
    display_names, addresses = _split_participants(raw)

    body: list[str] = []
    if snippet:
        body.append(snippet)
    if cfg.include_addresses and addresses:
        escaped = ", ".join(escape_wikilinks(a) for a in addresses)
        body.extend(["", f"**From:** {escaped}"])

    return _compose(
        folder="Email",
        domain="email",
        title=escape_wikilinks(subject_raw),
        date_str=date_str,
        year=year,
        month=month,
        slug=safe_segment(subject_raw, provider_id),
        tags=["email", "arshad-ai"] + display_names,
        body_lines=body,
    )


def render_github_note(row: Any, cfg: ExportConfig | None = None) -> RenderedNote:
    """Render an IngestedGitHubActivity row as a vault markdown note.

    Issue and PR rows with the same provider_id (number) get distinct
    vault paths because kind is included in both the slug base and the
    hash-gate suffix.

    URLs are written as plain text (not as Markdown links) to prevent any
    confusion with wikilink syntax.
    """
    raw: dict[str, Any] = getattr(row, "raw", {}) or {}
    date_str, year, month = date_parts(getattr(row, "occurred_at", None))
    provider_id = str(getattr(row, "provider_id", "") or "")
    kind = str(getattr(row, "kind", "") or "")  # 'issue' | 'pr'

    title_raw = str(raw.get("title") or "Untitled")
    html_url = str(raw.get("html_url") or "")
    body_raw = str(raw.get("body") or raw.get("description") or "")
    state = escape_wikilinks(str(raw.get("state") or ""))
    label_tags = [escape_wikilinks(str(lb)) for lb in (raw.get("labels") or []) if lb]

    body: list[str] = []
    if state:
        body.append(f"**State:** {state}")
    if html_url:
        # Plain text URL — no Markdown link syntax, no wikilinks.
        body.append(f"**URL:** {html_url}")
    if body_raw:
        body.extend(["", escape_wikilinks(body_raw)])

    return _compose(
        folder="GitHub",
        domain="github",
        title=escape_wikilinks(title_raw),
        date_str=date_str,
        year=year,
        month=month,
        # Include kind in both the slug base and the id_suffix so that an
        # issue and a PR with the same number produce different paths.
        slug=safe_segment(f"{kind}-{title_raw}", f"{kind}-{provider_id}"),
        tags=["github", "arshad-ai"] + ([kind] if kind else []) + label_tags,
        body_lines=body,
        extra_frontmatter={"kind": kind},
    )


__all__ = [
    "RenderedNote",
    "render_calendar_note",
    "render_email_note",
    "render_github_note",
]
