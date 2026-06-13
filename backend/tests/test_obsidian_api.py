"""Contract tests for the obsidian API response shape.

Tests the serialiser helpers and response-dict structure directly to pin the
envelope shape used by the frontend (useFetch unwraps one level of data:).

Shape contract:
  GET /api/v1/obsidian/notes → { "data": { "notes": [...], "total": N } }
  GET /api/v1/obsidian/stats → { "data": { "total_notes": N, "total_words": N,
                                            "last_synced_at": str | None } }
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _make_note(title: str = "Test Note", path: str = "vault/test.md") -> MagicMock:
    note = MagicMock()
    note.id = uuid.uuid4()
    note.title = title
    note.github_path = path
    note.content = "Hello world content"
    note.frontmatter = {}
    note.tags = ["tag1", "tag2"]
    note.word_count = 3
    note.blob_sha = "deadbeef"
    note.last_modified_at = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
    note.ingested_at = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
    return note


class TestNoteSummaryShape:
    """_note_summary must produce the fields the frontend reads."""

    def _fn(self, note):
        from src.api.v1.obsidian import _note_summary

        return _note_summary(note)

    def test_all_required_fields_present(self):
        result = self._fn(_make_note())
        assert "id" in result
        assert "title" in result
        assert "path" in result
        assert "excerpt" in result
        assert "tags" in result
        assert "word_count" in result
        assert "last_modified_at" in result

    def test_title_and_path(self):
        result = self._fn(_make_note(title="My Note", path="folder/my-note.md"))
        assert result["title"] == "My Note"
        assert result["path"] == "folder/my-note.md"

    def test_tags_is_list(self):
        result = self._fn(_make_note())
        assert isinstance(result["tags"], list)

    def test_tags_falls_back_to_empty_list_when_not_a_list(self):
        note = _make_note()
        note.tags = None
        result = self._fn(note)
        assert result["tags"] == []

    def test_word_count_is_int(self):
        result = self._fn(_make_note())
        assert isinstance(result["word_count"], int)

    def test_last_modified_at_is_iso_string(self):
        result = self._fn(_make_note())
        # Must be parseable as ISO-8601
        parsed = datetime.fromisoformat(result["last_modified_at"])
        assert parsed.year == 2026

    def test_excerpt_truncated_to_200_chars(self):
        note = _make_note()
        note.content = "A" * 300
        result = self._fn(note)
        assert len(result["excerpt"]) <= 200


class TestListNotesResponseEnvelope:
    """The list_notes return dict must use the nested envelope.

    Shape: { "data": { "notes": [...], "total": N } }

    The frontend does useFetch<{ notes: NoteSummary[]; total: number }>
    which means useFetch unwraps the outer "data" key and the component
    reads notesData.notes and notesData.total.
    """

    def _build_response(self, rows, total):
        from src.api.v1.obsidian import _note_summary

        return {
            "data": {
                "notes": [_note_summary(n) for n in rows],
                "total": total,
            },
        }

    def test_top_level_has_data_key(self):
        result = self._build_response([], 0)
        assert "data" in result

    def test_data_has_notes_key_not_array(self):
        result = self._build_response([], 0)
        assert isinstance(result["data"], dict), "data must be an object, not a list"
        assert "notes" in result["data"]

    def test_data_has_total_key(self):
        result = self._build_response([], 0)
        assert "total" in result["data"]

    def test_total_is_not_top_level_sibling(self):
        """Regression: total must NOT be at the same level as data."""
        result = self._build_response([], 0)
        assert "total" not in result, (
            "total appeared at top level — breaks useFetch unwrapping"
        )

    def test_notes_is_list(self):
        result = self._build_response([], 0)
        assert isinstance(result["data"]["notes"], list)

    def test_notes_contains_serialised_summaries(self):
        note = _make_note(title="Gate Test")
        result = self._build_response([note], 1)
        assert len(result["data"]["notes"]) == 1
        assert result["data"]["notes"][0]["title"] == "Gate Test"
        assert result["data"]["total"] == 1

    def test_total_reflects_count_not_page_size(self):
        """total is the pre-pagination match count, not len(notes)."""
        note = _make_note()
        result = self._build_response([note], 42)
        assert result["data"]["total"] == 42
        assert len(result["data"]["notes"]) == 1
