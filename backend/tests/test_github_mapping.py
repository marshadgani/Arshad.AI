"""Unit tests for ``src/services/ingestion/github_mapping.py``.

FEAT-139 gap: the ingestion integration tests in test_github_ingestion.py
exercise this module only indirectly (via ``ingest()``'s skipped_count),
so several pure-function edge cases were never actually asserted at the
boundary where they're implemented: a non-string ``updated_at`` (int from
a malformed payload), a valid tz-offset timestamp, and the ``provider_id``
prefix-collision guard that the dashboard's per-repo lookups depend on.
No I/O, no session, no mocks — this module takes plain dicts.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from src.services.ingestion.github_mapping import (
    build_activity_rows,
    build_provider_id,
    parse_github_timestamp,
)

# ── parse_github_timestamp ──────────────────────────────────────────


def test_parse_github_timestamp_valid_z_suffix():
    result = parse_github_timestamp("2024-03-15T12:00:00Z")
    assert isinstance(result, datetime)
    assert (result.year, result.month, result.day) == (2024, 3, 15)


def test_parse_github_timestamp_valid_tz_offset():
    result = parse_github_timestamp("2024-03-15T12:00:00+05:30")
    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_parse_github_timestamp_none_returns_none():
    assert parse_github_timestamp(None) is None


def test_parse_github_timestamp_empty_string_returns_none():
    assert parse_github_timestamp("") is None


def test_parse_github_timestamp_malformed_returns_none():
    assert parse_github_timestamp("not-a-date") is None


def test_parse_github_timestamp_non_string_type_returns_none():
    """A malformed proxy response could hand back an int/list instead of
    GitHub's documented str|null. Without the isinstance guard this would
    raise AttributeError out of .replace() and abort the whole repo."""
    assert parse_github_timestamp(12345) is None  # type: ignore[arg-type]
    assert parse_github_timestamp(["2024-03-15T12:00:00Z"]) is None  # type: ignore[arg-type]


# ── build_provider_id ────────────────────────────────────────────────


def test_build_provider_id_format():
    assert build_provider_id("marshadgani/Arshad.AI", 42) == "marshadgani/Arshad.AI#42"


def test_build_provider_id_no_prefix_collision():
    """'org/a'#123 and 'org/ab'#456 must not be confusable by any prefix
    match a caller might do against provider_id."""
    pid_a = build_provider_id("org/a", 123)
    pid_ab = build_provider_id("org/ab", 456)

    assert pid_a == "org/a#123"
    assert not pid_ab.startswith("org/a#")


# ── build_activity_rows ──────────────────────────────────────────────


def _issue(number, updated_at="2024-03-15T12:00:00Z"):
    return {"number": number, "title": f"issue {number}", "updated_at": updated_at}


def test_build_activity_rows_valid_batch():
    user_id = uuid.uuid4()
    batch = build_activity_rows(
        user_id=user_id,
        repo="org/repo",
        kind="issue",
        items=[_issue(1), _issue(2)],
    )

    assert batch.skipped_count == 0
    assert len(batch.rows) == 2
    for row in batch.rows:
        assert row["user_id"] == user_id
        assert row["kind"] == "issue"
        assert row["provider_id"].startswith("org/repo#")
        assert isinstance(row["occurred_at"], datetime)
        assert row["raw"]["number"] in (1, 2)


def test_build_activity_rows_skips_item_without_number():
    batch = build_activity_rows(
        user_id=uuid.uuid4(),
        repo="org/repo",
        kind="issue",
        items=[{"title": "no number"}, _issue(5)],
    )

    assert batch.skipped_count == 1
    assert len(batch.rows) == 1
    assert batch.rows[0]["provider_id"] == "org/repo#5"


def test_build_activity_rows_skips_malformed_updated_at():
    batch = build_activity_rows(
        user_id=uuid.uuid4(),
        repo="org/repo",
        kind="issue",
        items=[
            _issue(3, updated_at="not-a-date"),
            _issue(4, updated_at=None),
            _issue(5),
        ],
    )

    assert batch.skipped_count == 2
    assert len(batch.rows) == 1
    assert batch.rows[0]["provider_id"] == "org/repo#5"


def test_build_activity_rows_empty_input():
    batch = build_activity_rows(
        user_id=uuid.uuid4(), repo="org/repo", kind="pr", items=[]
    )
    assert batch.rows == []
    assert batch.skipped_count == 0
