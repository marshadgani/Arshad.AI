"""Unit tests for src.services.drive._classify.classify_files.

All tests are synchronous, fixture-free, and use a fixed clock.
NO I/O occurs in this file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from src.services.drive._classify import classify_files

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
STALE = 180  # default


def _file(
    file_id="file-001",
    name="test-doc.pdf",
    modified_time=None,
    web_view_link="https://drive.google.com/file/d/file-001",
    permissions=None,
):
    """Build a minimal Drive v3 file dict."""
    mt = modified_time or (NOW - timedelta(days=200)).isoformat()
    return {
        "id": file_id,
        "name": name,
        "modifiedTime": mt,
        "webViewLink": web_view_link,
        "permissions": permissions
        if permissions is not None
        else [
            {"id": "p1", "type": "user", "role": "owner"},
        ],
    }


def _perm(ptype="user", role="reader", allow_discovery=None):
    p = {"id": "px", "type": ptype, "role": role}
    if allow_discovery is not None:
        p["allowFileDiscovery"] = allow_discovery
    return p


# ---------------------------------------------------------------------------
# FN-102 — anyone_with_link detection
# ---------------------------------------------------------------------------


class TestAnyoneWithLink:
    def test_anyone_with_link_true_when_type_anyone(self):
        f = _file(permissions=[_perm("anyone", "reader")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].anyone_with_link is True

    def test_anyone_with_link_true_regardless_of_allow_file_discovery(self):
        f = _file(permissions=[_perm("anyone", "reader", allow_discovery=False)])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].anyone_with_link is True

    def test_anyone_with_link_false_for_user_type(self):
        f = _file(permissions=[_perm("user", "reader")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].anyone_with_link is False

    def test_anyone_with_link_false_for_group_type(self):
        f = _file(permissions=[_perm("group", "reader")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].anyone_with_link is False

    def test_anyone_with_link_false_for_domain_type(self):
        f = _file(permissions=[_perm("domain", "reader")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].anyone_with_link is False

    def test_anyone_with_link_none_when_permissions_missing(self):
        """Non-owner file — permissions list absent."""
        f = _file(permissions=[])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].anyone_with_link is None
        assert result[0].permissions_visible is False

    def test_anyone_with_link_none_when_permissions_none(self):
        f = {
            "id": "f1",
            "name": "n",
            "modifiedTime": NOW.isoformat(),
            "permissions": None,
        }
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].anyone_with_link is None


# ---------------------------------------------------------------------------
# FN-102 — permissions_visible
# ---------------------------------------------------------------------------


class TestPermissionsVisible:
    def test_visible_true_when_permissions_non_empty(self):
        f = _file(permissions=[_perm()])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].permissions_visible is True

    def test_visible_false_empty_list(self):
        f = _file(permissions=[])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].permissions_visible is False

    def test_invisible_file_never_reported_as_safe(self):
        """When permissions_visible=False, both link flags must be None, not safe."""
        f = _file(permissions=[])
        r = classify_files([f], now=NOW, stale_days=STALE)[0]
        assert r.permissions_visible is False
        assert r.anyone_with_link is None
        assert r.stale_sharing is None


# ---------------------------------------------------------------------------
# FN-103 — stale_sharing proxy (NF-203 clock injection)
# ---------------------------------------------------------------------------


class TestStaleSharing:
    def test_stale_sharing_true_when_file_old_and_shared(self):
        old_time = (NOW - timedelta(days=STALE + 1)).isoformat()
        f = _file(
            modified_time=old_time,
            permissions=[_perm("user", "reader"), _perm("user", "owner")],
        )
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].stale_sharing is True

    def test_stale_sharing_false_at_exact_boundary(self):
        """Age == stale_days exactly is NOT stale (strictly less-than check)."""
        exact = (NOW - timedelta(days=STALE)).isoformat()
        f = _file(modified_time=exact, permissions=[_perm("user", "reader")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].stale_sharing is False

    def test_stale_sharing_true_one_second_past_boundary(self):
        just_past = (NOW - timedelta(days=STALE) - timedelta(seconds=1)).isoformat()
        f = _file(modified_time=just_past, permissions=[_perm("user", "reader")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].stale_sharing is True

    def test_stale_sharing_false_for_recently_modified(self):
        recent = (NOW - timedelta(days=10)).isoformat()
        f = _file(modified_time=recent, permissions=[_perm("user", "reader")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].stale_sharing is False

    @pytest.mark.parametrize("days", [1, 180, 3650])
    def test_stale_days_parametrised(self, days):
        old_time = (NOW - timedelta(days=days + 1)).isoformat()
        f = _file(modified_time=old_time, permissions=[_perm("user", "reader")])
        result = classify_files([f], now=NOW, stale_days=days)
        assert result[0].stale_sharing is True

    def test_clock_injection_moving_now_forward_flips_stale(self):
        """NF-203: same file becomes stale when the clock moves forward."""
        mt = (NOW - timedelta(days=100)).isoformat()
        f = _file(modified_time=mt, permissions=[_perm("user", "reader")])
        assert classify_files([f], now=NOW, stale_days=180)[0].stale_sharing is False
        future = NOW + timedelta(days=100)
        assert classify_files([f], now=future, stale_days=180)[0].stale_sharing is True

    def test_classify_files_never_calls_datetime_now(self, monkeypatch):
        """NF-203 dynamic guard: classify_files must not call datetime.now() or
        datetime.utcnow() — it must use only the injected `now` parameter.

        We intercept only the forbidden clock-reading methods, leaving
        fromisoformat() and timezone alone so timestamp parsing still works.
        """
        from datetime import datetime as _real_datetime

        import src.services.drive._classify as mod

        class ClockGuardedDatetime(_real_datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                raise AssertionError(
                    "datetime.now() called inside classify_files — inject the clock"
                )

            @classmethod
            def utcnow(cls):
                raise AssertionError(
                    "datetime.utcnow() called inside classify_files — inject the clock"
                )

        monkeypatch.setattr(mod, "datetime", ClockGuardedDatetime)
        # Must not raise — fromisoformat/timezone still work, clock calls are blocked
        f = _file(permissions=[_perm()])
        classify_files([f], now=NOW, stale_days=STALE)

    def test_stale_sharing_none_when_permissions_not_visible(self):
        f = _file(permissions=[])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].stale_sharing is None

    def test_only_owner_permission_means_not_shared(self):
        """A file shared with only the owner is not stale-shared."""
        old_time = (NOW - timedelta(days=400)).isoformat()
        f = _file(modified_time=old_time, permissions=[_perm("user", "owner")])
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].stale_sharing is False


# ---------------------------------------------------------------------------
# modifiedTime parsing edge cases
# ---------------------------------------------------------------------------


class TestModifiedTimeParsing:
    def test_z_suffix_parsed(self):
        f = _file(modified_time="2025-01-01T00:00:00Z", permissions=[_perm()])
        result = classify_files([f], now=NOW, stale_days=1)
        assert result[0].stale_sharing is True

    def test_offset_suffix_parsed(self):
        f = _file(modified_time="2025-01-01T00:00:00+00:00", permissions=[_perm()])
        result = classify_files([f], now=NOW, stale_days=1)
        assert result[0].stale_sharing is True

    def test_fractional_seconds_parsed(self):
        f = _file(modified_time="2025-06-01T12:34:56.789Z", permissions=[_perm()])
        result = classify_files([f], now=NOW, stale_days=1)
        # file is before NOW, so stale
        assert result[0].stale_sharing is True

    def test_naive_timestamp_treated_as_utc(self):
        f = _file(modified_time="2025-01-01T00:00:00", permissions=[_perm()])
        result = classify_files([f], now=NOW, stale_days=1)
        assert result[0].stale_sharing is True

    def test_malformed_timestamp_yields_unknown_not_raise(self):
        """An unparseable modifiedTime gives stale_sharing=None (unknown), no crash."""
        f = _file(modified_time="NOT-A-DATE", permissions=[_perm()])
        result = classify_files([f], now=NOW, stale_days=STALE)
        # None means unknown — cannot determine staleness without a timestamp.
        # It is NOT False (safe); it is unknown/unresolvable.
        assert result[0].stale_sharing is None
        assert result[0].id == f["id"]

    def test_missing_modified_time_yields_unknown(self):
        """A missing modifiedTime gives stale_sharing=None (unknown), not False."""
        f = {"id": "x1", "name": "doc", "permissions": [_perm()]}
        result = classify_files([f], now=NOW, stale_days=STALE)
        assert result[0].stale_sharing is None


# ---------------------------------------------------------------------------
# Output shape and safety
# ---------------------------------------------------------------------------


class TestOutputShape:
    def test_empty_input_returns_empty_list(self):
        assert classify_files([], now=NOW, stale_days=STALE) == []

    def test_output_order_equals_input_order(self):
        files = [_file(file_id=f"f{i}") for i in range(5)]
        result = classify_files(files, now=NOW, stale_days=STALE)
        assert [r.id for r in result] == [f"f{i}" for i in range(5)]

    def test_does_not_mutate_input_dicts(self):
        f = _file()
        original_keys = set(f.keys())
        classify_files([f], now=NOW, stale_days=STALE)
        assert set(f.keys()) == original_keys

    def test_output_has_no_email_field(self):
        perms = [
            {
                "id": "p1",
                "type": "user",
                "role": "reader",
                "emailAddress": "secret@example.com",
            }
        ]
        f = _file(permissions=perms)
        r = classify_files([f], now=NOW, stale_days=STALE)[0]
        assert not hasattr(r, "emailAddress")
        assert not hasattr(r, "email")

    def test_missing_web_view_link_uses_empty_string(self):
        f = {
            "id": "f1",
            "name": "doc",
            "modifiedTime": NOW.isoformat(),
            "permissions": [_perm()],
        }
        r = classify_files([f], now=NOW, stale_days=STALE)[0]
        assert r.web_view_link == ""

    def test_missing_name_uses_empty_string(self):
        f = {"id": "f1", "modifiedTime": NOW.isoformat(), "permissions": [_perm()]}
        r = classify_files([f], now=NOW, stale_days=STALE)[0]
        assert r.name == ""

    def test_non_dict_entries_skipped(self):
        result = classify_files([None, "bad", {"id": ""}], now=NOW, stale_days=STALE)
        assert result == []

    def test_file_without_id_skipped(self):
        f = {"name": "doc", "modifiedTime": NOW.isoformat()}
        assert classify_files([f], now=NOW, stale_days=STALE) == []
