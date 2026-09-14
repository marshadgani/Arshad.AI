"""Regression test for the naive-datetime fallout of FEAT-157.

`_parse_event_start` (calendar) and `_parse_iso` (github) both feed
`occurred_at`, a TIMESTAMP WITH TIME ZONE column — an all-day Google
Calendar event's `start.date` (e.g. "2026-09-14", no offset) parses to a
naive datetime via `datetime.fromisoformat`, which asyncpg rejects with
the same "can't subtract offset-naive and offset-aware datetimes" error
FEAT-157 fixed elsewhere. Both parsers now treat an offset-less parsed
value as UTC instead of returning it naive.
"""

from src.services.ingestion.calendar import _parse_event_start
from src.services.ingestion.github import _parse_iso


def test_parse_event_start_all_day_date_is_timezone_aware():
    result = _parse_event_start({"start": {"date": "2026-09-14"}})
    assert result.tzinfo is not None


def test_parse_event_start_timed_event_is_timezone_aware():
    result = _parse_event_start(
        {"start": {"dateTime": "2026-09-14T10:00:00Z"}}
    )
    assert result.tzinfo is not None


def test_parse_event_start_missing_start_is_timezone_aware():
    assert _parse_event_start({}).tzinfo is not None


def test_parse_iso_offset_less_value_is_timezone_aware():
    result = _parse_iso("2026-09-14T10:00:00")
    assert result.tzinfo is not None


def test_parse_iso_zulu_value_is_timezone_aware():
    result = _parse_iso("2026-09-14T10:00:00Z")
    assert result.tzinfo is not None


def test_parse_iso_missing_value_is_timezone_aware():
    assert _parse_iso(None).tzinfo is not None
