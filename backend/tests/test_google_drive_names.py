"""Unit tests for knowledge-suggestion name normalisation in DriveAuditService.

Tests exercise the KnowledgeSuggestionsResult-building logic in service.py
by constructing Integration stubs with scripted config dicts.
All synchronous; no I/O.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from src.services.drive import DriveAuditService
from src.services.drive._constants import _MAX_NAME_CHARS, _MAX_SUGGESTIONS


def _integration(files, file_count=None, truncated_flag=False, status="connected"):
    config = {"files": files}
    if file_count is not None:
        config["file_count"] = file_count
    if truncated_flag:
        config["truncated"] = True
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        slug="google_drive",
        status=status,
        config=config,
        last_error=None,
    )


def _db(integration):
    """Minimal DB stub that returns the given integration on the first execute."""

    class _Result:
        def scalar_one_or_none(self):
            return integration

    class _DB:
        async def execute(self, stmt):
            return _Result()

        async def commit(self):
            pass

    return _DB()


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# NF-209 — truncation to 512 chars
# ---------------------------------------------------------------------------


class TestNameTruncation:
    def test_name_at_511_chars_kept_as_is(self):
        name = "A" * 511
        intg = _integration([{"id": "f1", "name": name}])
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names[0] == name

    def test_name_at_512_chars_kept(self):
        name = "B" * 512
        intg = _integration([{"id": "f1", "name": name}])
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names[0] == name

    def test_name_at_513_chars_truncated_to_512(self):
        name = "C" * 513
        intg = _integration([{"id": "f1", "name": name}])
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert len(result.names[0]) == _MAX_NAME_CHARS

    def test_very_long_name_truncated(self):
        name = "X" * 10000
        intg = _integration([{"id": "f1", "name": name}])
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert len(result.names[0]) == _MAX_NAME_CHARS


# ---------------------------------------------------------------------------
# NF-209 — deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_exact_duplicate_names_deduped(self):
        files = [{"id": f"f{i}", "name": "Report.pdf"} for i in range(3)]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names.count("Report.pdf") == 1

    def test_different_names_both_kept(self):
        files = [{"id": "f1", "name": "A.pdf"}, {"id": "f2", "name": "B.pdf"}]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert set(result.names) == {"A.pdf", "B.pdf"}

    def test_case_differing_names_kept_separately(self):
        """Exact-value dedup: 'doc.pdf' and 'Doc.pdf' are different."""
        files = [{"id": "f1", "name": "doc.pdf"}, {"id": "f2", "name": "Doc.pdf"}]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert len(result.names) == 2

    def test_total_equals_len_data_after_dedup(self):
        files = [{"id": f"f{i}", "name": "same"} for i in range(5)]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.total == len(result.names)


# ---------------------------------------------------------------------------
# Filtering invalid entries
# ---------------------------------------------------------------------------


class TestInvalidEntries:
    def test_empty_name_dropped(self):
        files = [{"id": "f1", "name": ""}]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names == []

    def test_whitespace_only_name_dropped(self):
        files = [{"id": "f1", "name": "   "}]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names == []

    def test_non_string_name_dropped(self):
        files = [{"id": "f1", "name": 12345}]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names == []

    def test_non_dict_entry_in_files_list_skipped(self):
        intg = _integration(["not-a-dict", None, {"id": "f1", "name": "valid.pdf"}])
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names == ["valid.pdf"]


# ---------------------------------------------------------------------------
# NF-209 — truncated flag
# ---------------------------------------------------------------------------


class TestTruncatedFlag:
    def test_truncated_false_when_file_count_equals_cached(self):
        files = [{"id": "f1", "name": "a.pdf"}]
        intg = _integration(files, file_count=1)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.truncated is False

    def test_truncated_true_when_file_count_exceeds_cached(self):
        files = [{"id": "f1", "name": "a.pdf"}]
        intg = _integration(files, file_count=5)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.truncated is True

    def test_truncated_true_from_integration_config_flag(self):
        files = [{"id": "f1", "name": "a.pdf"}]
        intg = _integration(files, truncated_flag=True)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.truncated is True

    def test_truncated_true_when_unique_names_exceed_max_suggestions(self):
        files = [
            {"id": f"f{i}", "name": f"file_{i}.pdf"}
            for i in range(_MAX_SUGGESTIONS + 5)
        ]
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.truncated is True
        assert len(result.names) <= _MAX_SUGGESTIONS


# ---------------------------------------------------------------------------
# Edge: None / empty config
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_config_returns_empty_without_raising(self):
        intg = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            slug="google_drive",
            status="connected",
            config=None,
            last_error=None,
        )
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names == []
        assert result.connected is True

    def test_missing_files_key_returns_empty(self):
        intg = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            slug="google_drive",
            status="connected",
            config={},
            last_error=None,
        )
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names == []

    def test_old_cached_rows_lacking_web_view_link_still_yield_names(self):
        files = [{"id": "f1", "name": "old.pdf"}]  # no web_view_link or modified_time
        intg = _integration(files)
        result = run(
            DriveAuditService.get_knowledge_suggestions(intg.user_id, _db(intg))
        )
        assert result.names == ["old.pdf"]
