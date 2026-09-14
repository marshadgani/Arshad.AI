"""Pure-function tests for the outbound Obsidian export renderers.

No mocks — renderers take a row-like object and return (path, content,
title, frontmatter) with no DB/HTTP access.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from src.services.ingestion.obsidian import _parse_frontmatter
from src.services.obsidian.config import EXPORT_ROOT, ExportConfig
from src.services.obsidian.markdown import (
    escape_wikilinks as _escape_wikilinks,
)
from src.services.obsidian.markdown import (
    safe_segment as _safe_segment,
)
from src.services.obsidian.renderers import (
    render_calendar_note,
    render_email_note,
    render_github_note,
)


def _row(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        occurred_at=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        provider_id="evt-123",
        raw={},
        ingested_at=datetime(2026, 6, 12, 9, 5, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestSafeSegment:
    def test_collision_resistance_via_hash_suffix(self):
        a = _safe_segment("a" * 100, "id-1")
        b = _safe_segment("a" * 100, "id-2")
        assert a != b

    def test_strips_unsafe_chars(self):
        segment = _safe_segment("Hello, World! / Path\\Traversal", "id-3")
        assert all(c.isalnum() or c in "-" for c in segment)

    def test_never_empty(self):
        assert _safe_segment("", "id-4") != ""


class TestWikilinkEscaping:
    def test_escapes_double_brackets(self):
        assert _escape_wikilinks("[[Secret Note]]") == r"\[\[Secret Note\]\]"

    def test_leaves_normal_text_untouched(self):
        assert _escape_wikilinks("Just a normal subject") == "Just a normal subject"


class TestCalendarRenderer:
    def test_path_under_export_root(self):
        row = _row(raw={"summary": "Team Sync"})
        note = render_calendar_note(row)
        assert note.path.startswith(f"{EXPORT_ROOT}Calendar/2026/06/")
        assert note.path.endswith(".md")

    def test_wikilink_injection_in_summary_is_neutralised(self):
        row = _row(raw={"summary": "[[Malicious Link]] meeting"})
        note = render_calendar_note(row)
        assert "[[Malicious Link]]" not in note.content
        assert r"\[\[Malicious Link\]\]" in note.content

    def test_frontmatter_round_trips_through_inbound_parser(self):
        row = _row(
            raw={"summary": 'Weird: title with "quotes" and --- dashes\nnewline'}
        )
        note = render_calendar_note(row)
        fm, body = _parse_frontmatter(note.content)
        # The inbound regex parser doesn't strip quotes off scalar values
        # (only off list items) — the JSON encoding survives structurally
        # intact (single line, no stray '---', no crash) even though the
        # value itself keeps its quotes. That's fine: exported notes are
        # excluded from re-ingestion entirely (EXPORT_ROOT prefix skip in
        # services/ingestion/obsidian.py), so this parser never actually
        # sees them in production — this test only proves the block can't
        # corrupt or desync the parser if it ever did.
        assert fm["domain"] == '"calendar"'
        assert "tags" in fm


class TestEmailRenderer:
    def test_snippet_capped(self):
        row = _row(raw={"subject": "Long thread", "snippet": "x" * 2000})
        note = render_email_note(row, ExportConfig(snippet_max_chars=50))
        # frontmatter block + heading + capped snippet
        assert "x" * 51 not in note.content

    def test_no_raw_addresses_in_frontmatter(self):
        row = _row(
            raw={
                "subject": "Invoice",
                "participants": ["Jane Doe"],
                "from": ["jane@example.com"],
            }
        )
        note = render_email_note(row, ExportConfig(include_addresses=False))
        assert "jane@example.com" not in note.content
        assert "Jane Doe" in note.frontmatter["tags"]

    def test_address_shaped_participants_are_kept_out_of_tags(self):
        """`participants` is provider-shaped and routinely carries bare or
        angle-bracketed addresses — those must never reach frontmatter
        tags, which are written regardless of include_addresses."""
        row = _row(
            raw={
                "subject": "Invoice",
                "participants": [
                    "Jane Doe",
                    "bare@example.com",
                    "Bob Smith <bob@example.com>",
                ],
            }
        )
        note = render_email_note(row, ExportConfig(include_addresses=False))
        # Every renderer emits [domain, "arshad-ai", *extra] — domain first.
        assert note.frontmatter["tags"] == ["email", "arshad-ai", "Jane Doe"]
        assert "bare@example.com" not in note.content
        assert "bob@example.com" not in note.content

    def test_addresses_only_with_explicit_opt_in(self):
        row = _row(raw={"subject": "Invoice", "from": ["jane@example.com"]})
        note = render_email_note(row, ExportConfig(include_addresses=True))
        assert "jane@example.com" in note.content


class TestGithubRenderer:
    def test_issue_and_pr_with_same_number_do_not_collide(self):
        issue = _row(kind="issue", provider_id="42", raw={"title": "Bug report"})
        pr = _row(kind="pr", provider_id="42", raw={"title": "Bug report"})
        note_issue = render_github_note(issue)
        note_pr = render_github_note(pr)
        assert note_issue.path != note_pr.path

    def test_no_markdown_or_wiki_link_syntax_for_url(self):
        row = _row(
            kind="pr",
            provider_id="99",
            raw={"title": "Fix bug", "html_url": "https://github.com/x/y/pull/99"},
        )
        note = render_github_note(row)
        assert "[[" not in note.content
        assert "](https://github.com/x/y/pull/99)" not in note.content
        assert "https://github.com/x/y/pull/99" in note.content
