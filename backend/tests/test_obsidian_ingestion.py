"""Unit tests for Obsidian ingestion helpers and intent classifier.

Covers:
  - _parse_frontmatter: no frontmatter, complete frontmatter, array values, unterminated block
  - _extract_tags: fm tags list, fm tags string, inline #hashtags, dedup
  - _extract_title: fm title, H1 heading, path stem fallback
  - _word_count: empty, single word, multi-word
  - intent_classifier._fast_path: obsidian keywords
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def _fn(self, text):
        from src.services.ingestion.obsidian import _parse_frontmatter

        return _parse_frontmatter(text)

    def test_no_frontmatter_returns_empty_dict_and_full_body(self):
        body = "# Hello\nsome text"
        fm, b = self._fn(body)
        assert fm == {}
        assert b == body

    def test_basic_frontmatter_parsed(self):
        content = "---\ntitle: My Note\nauthor: Arshad\n---\nBody text"
        fm, body = self._fn(content)
        assert fm["title"] == "My Note"
        assert fm["author"] == "Arshad"
        assert body == "Body text"

    def test_array_value_parsed(self):
        content = "---\ntags: [python, ai, llm]\n---\nContent"
        fm, _ = self._fn(content)
        assert fm["tags"] == ["python", "ai", "llm"]

    def test_array_with_quoted_values(self):
        content = '---\ntags: ["one", "two"]\n---\nContent'
        fm, _ = self._fn(content)
        assert fm["tags"] == ["one", "two"]

    def test_unterminated_frontmatter_ignored(self):
        content = "---\ntitle: No End\nContent still here"
        fm, body = self._fn(content)
        assert fm == {}
        assert body == content

    def test_body_leading_newlines_stripped(self):
        content = "---\ntitle: Test\n---\n\n\nActual body"
        _, body = self._fn(content)
        assert body.startswith("Actual body")


# ---------------------------------------------------------------------------
# _extract_tags
# ---------------------------------------------------------------------------


class TestExtractTags:
    def _fn(self, fm, body):
        from src.services.ingestion.obsidian import _extract_tags

        return _extract_tags(fm, body)

    def test_tags_from_fm_list(self):
        tags = self._fn({"tags": ["python", "ai"]}, "no inline tags here")
        assert "python" in tags
        assert "ai" in tags

    def test_tags_from_fm_string(self):
        tags = self._fn({"tags": "python, ai, llm"}, "")
        assert "python" in tags
        assert "ai" in tags
        assert "llm" in tags

    def test_fm_tags_with_hash_stripped(self):
        tags = self._fn({"tags": ["#python", "#ai"]}, "")
        assert "python" in tags
        assert "ai" in tags
        assert "#python" not in tags

    def test_inline_hashtags_extracted(self):
        body = "This is about #python and #machine-learning"
        tags = self._fn({}, body)
        assert "python" in tags
        assert "machine-learning" in tags

    def test_no_duplicate_tags(self):
        body = "Using #python here and #python there"
        tags = self._fn({"tags": ["python"]}, body)
        assert tags.count("python") == 1

    def test_empty_inputs(self):
        tags = self._fn({}, "")
        assert tags == []


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def _fn(self, fm, body, path):
        from src.services.ingestion.obsidian import _extract_title

        return _extract_title(fm, body, path)

    def test_fm_title_wins(self):
        assert (
            self._fn({"title": "FM Title"}, "# H1 Title", "notes/file.md") == "FM Title"
        )

    def test_h1_heading_used_when_no_fm_title(self):
        assert (
            self._fn({}, "# My Heading\nsome content", "notes/file.md") == "My Heading"
        )

    def test_path_stem_used_as_fallback(self):
        assert (
            self._fn({}, "no heading here", "Daily Notes/2026-06-12.md") == "2026-06-12"
        )

    def test_h1_must_be_at_line_start(self):
        body = "some text\n# Real Heading\nmore"
        assert self._fn({}, body, "file.md") == "Real Heading"

    def test_fm_title_empty_string_falls_back_to_h1(self):
        assert self._fn({"title": ""}, "# H1\n", "file.md") == "H1"


# ---------------------------------------------------------------------------
# _word_count
# ---------------------------------------------------------------------------


class TestWordCount:
    def _fn(self, text):
        from src.services.ingestion.obsidian import _word_count

        return _word_count(text)

    def test_empty_string(self):
        assert self._fn("") == 0

    def test_single_word(self):
        assert self._fn("hello") == 1

    def test_multiple_words(self):
        assert self._fn("hello world foo bar") == 4

    def test_leading_trailing_whitespace(self):
        assert self._fn("  hello world  ") == 2


# ---------------------------------------------------------------------------
# intent_classifier — obsidian fast-path
# ---------------------------------------------------------------------------


class TestObsidianFastPath:
    def _fn(self, text):
        from src.services.intent_classifier import _fast_path

        return _fast_path(text)

    def test_obsidian_keyword(self):
        assert self._fn("Search my obsidian notes") == "obsidian"

    def test_vault_keyword(self):
        assert self._fn("What's in my vault?") == "obsidian"

    def test_my_notes_keyword(self):
        assert self._fn("Show me my notes about Python") == "obsidian"

    def test_second_brain_keyword(self):
        assert self._fn("Search my second brain") == "obsidian"

    def test_knowledge_base_keyword(self):
        assert self._fn("Look through my knowledge base") == "obsidian"

    def test_i_wrote_keyword(self):
        assert self._fn("Do you remember what I wrote about React?") == "obsidian"

    def test_non_obsidian_not_matched(self):
        assert self._fn("Tell me about the weather") != "obsidian"
