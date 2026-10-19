"""FEAT-132: the log level must survive every step up to classification."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from src.services.render import client as render_client
from src.services.render import verdict
from src.services.render.models import LogRecord

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _rec(level, offset=0):
    return LogRecord(
        timestamp=NOW + timedelta(seconds=offset), level=level, message="m"
    )


def test_level_field_required():
    with pytest.raises(ValidationError):
        LogRecord(timestamp=NOW, message="x")


def test_level_coerces_unknown_string():
    assert _rec("trace").level == "unknown"
    assert _rec("WARN").level == "warning"


def test_classify_logs_uses_attribute():
    counts = verdict.classify_logs([_rec("error"), _rec("info"), _rec("critical")])
    assert counts["error"] == 1 and counts["critical"] == 1 and counts["info"] == 1


def test_classify_logs_dict_raises():
    with pytest.raises(AttributeError):
        verdict.classify_logs([{"level": "error", "message": "x", "timestamp": NOW}])


def test_classify_logs_plain_string_raises():
    with pytest.raises(AttributeError):
        verdict.classify_logs(["error: boom"])


def test_level_survives_parse_and_windowing():
    entry = {
        "timestamp": "2026-10-19T11:00:00Z",
        "message": "boom",
        "labels": [
            {"name": "level", "value": "error"},
            {"name": "type", "value": "app"},
        ],
    }
    parsed = render_client._parse_log(entry)
    assert parsed.level == "error" and parsed.resource_type == "app"
    windows = verdict.compute_windows(
        NOW, NOW + timedelta(minutes=2), NOW + timedelta(hours=3)
    )
    assert windows is not None
    assert verdict._error_count([parsed]) == 1


def test_different_levels_produce_different_counts():
    as_error = [_rec("error", i) for i in range(5)]
    as_info = [_rec("info", i) for i in range(5)]
    assert verdict._error_count(as_error) == 5
    assert verdict._error_count(as_info) == 0
