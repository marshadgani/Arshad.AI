"""Gate fixes for FEAT-123: malformed replies, field types, link allowlist,
never-synced cache, and the route rate limit."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import src.services.drive._errors as errors_mod
import src.services.drive.service as svc_mod
from src.services.drive import DriveAuditService
from src.services.drive._classify import classify_files
from src.services.drive._http import MalformedDriveResponse

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
USER = uuid.uuid4()


def run(coro):
    return asyncio.run(coro)


def _intg(status="connected", config=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=USER,
        slug="google_drive",
        status=status,
        config=config,
        last_error=None,
    )


class _DB:
    def __init__(self, intg):
        self._intg = intg

    async def execute(self, stmt):
        row = self._intg

        class _R:
            def scalar_one_or_none(self):
                return row

        return _R()

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    async def _tok(uid, db):
        return "tok"

    monkeypatch.setattr(errors_mod, "get_valid_google_token", _tok)

    async def _mark(integration, db):
        return None

    monkeypatch.setattr(svc_mod, "mark_healthy", _mark)


def _file(**kw):
    base = {"id": "f1", "name": "a.txt", "modifiedTime": "2020-01-01T00:00:00Z"}
    base.update(kw)
    return base


class TestFieldTypes:
    @pytest.mark.parametrize(
        "bad",
        [
            {"name": 123},
            {"modifiedTime": 12345},
            {"webViewLink": ["x"]},
            {"id": 7},
        ],
    )
    def test_wrong_field_type_is_dropped_not_a_crash(self, bad):
        out = classify_files([_file(**bad)], now=NOW, stale_days=180)
        assert out == []

    def test_only_google_links_are_relayed(self):
        good = _file(id="g", webViewLink="https://drive.google.com/file/d/g/view")
        docs = _file(id="d", webViewLink="https://docs.google.com/document/d/d")
        evil = _file(id="e", webViewLink="javascript:alert(1)")
        other = _file(id="o", webViewLink="https://evil.example/x")
        out = {
            r.id: r.web_view_link
            for r in classify_files([good, docs, evil, other], now=NOW, stale_days=1)
        }
        assert out["g"].startswith("https://drive.google.com/")
        assert out["d"].startswith("https://docs.google.com/")
        assert out["e"] == "" and out["o"] == ""


class TestMalformedReply:
    def test_malformed_reply_is_flagged_and_does_not_poison_status(self, monkeypatch):
        async def _list(token, *, limit, **kw):
            raise MalformedDriveResponse("no list")

        monkeypatch.setattr(svc_mod, "list_recent_files", _list)
        intg = _intg(config={})
        res = run(
            DriveAuditService.get_audit_results(
                USER, _DB(intg), limit=20, stale_days=180, now=NOW
            )
        )
        assert res.connected is True and res.files == []
        assert res.partial_failures == ["google_drive: malformed_response"]
        assert intg.status == "connected"
        assert intg.last_error is None


class TestKnowledgeCache:
    def _suggest(self, intg):
        return run(DriveAuditService.get_knowledge_suggestions(USER, _DB(intg)))

    def test_connected_but_never_synced_is_flagged(self):
        res = self._suggest(_intg(config={}))
        assert res.names == []
        assert "google_drive: not_synced" in res.partial_failures

    def test_synced_empty_drive_is_not_flagged(self):
        res = self._suggest(_intg(config={"files": [], "file_count": 0}))
        assert res.partial_failures == []

    def test_unreadable_cache_entries_are_flagged(self):
        res = self._suggest(
            _intg(config={"files": [{"name": "ok.txt"}, {"name": 5}, "junk"]})
        )
        assert res.names == ["ok.txt"]
        assert "google_drive: cache_unreadable" in res.partial_failures

    def test_every_entry_unreadable_is_not_a_clean_empty_list(self):
        res = self._suggest(_intg(config={"files": [None, {"name": ""}]}))
        assert res.names == []
        assert res.partial_failures == ["google_drive: cache_unreadable"]


class TestRouteRateLimit:
    def test_limit_is_enforced_before_any_drive_call(self, monkeypatch):
        from fastapi import HTTPException
        from fastapi.testclient import TestClient
        from src.api.v1 import drive as drive_route
        from src.auth.dependencies import get_current_user
        from src.main import app
        from src.models.database import get_db

        calls = []

        async def _deny(**kw):
            calls.append(kw)
            raise HTTPException(status_code=429, detail="slow down")

        async def _never(*a, **kw):
            raise AssertionError("Drive must not be called when rate limited")

        monkeypatch.setattr(drive_route, "enforce_rate_limit", _deny)
        monkeypatch.setattr(
            drive_route.DriveAuditService, "get_audit_results", staticmethod(_never)
        )
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER)

        async def _db():
            yield SimpleNamespace()

        app.dependency_overrides[get_db] = _db
        try:
            r = TestClient(app, raise_server_exceptions=False).get(
                "/api/v1/drive/permissions-audit"
            )
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 429
        assert calls and calls[0]["bucket"] == "drive_audit"
        assert calls[0]["identity"] == str(USER)


class TestIsolationAndRollback:
    def test_integration_lookup_filters_on_the_caller(self):
        """The query itself must pin the row to the caller (a stub DB cannot)."""
        from src.services.integrations.state import find_integration

        captured = {}

        class _Capture:
            async def execute(self, stmt):
                captured["sql"] = str(stmt.compile())
                captured["params"] = list(stmt.compile().params.values())

                class _R:
                    def scalar_one_or_none(self):
                        return None

                return _R()

        run(find_integration(USER, "google_drive", _Capture()))
        assert "integrations.user_id" in captured["sql"]
        assert USER in captured["params"]
        assert "user_id IS NULL" not in captured["sql"]

    def test_commit_and_rollback_both_failing_still_returns(self, monkeypatch):
        async def _list(token, *, limit, **kw):
            return [], False

        monkeypatch.setattr(svc_mod, "list_recent_files", _list)

        class _Broken(_DB):
            async def commit(self):
                raise RuntimeError("db down")

            async def rollback(self):
                raise RuntimeError("rollback also down")

        res = run(
            DriveAuditService.get_audit_results(
                USER, _Broken(_intg(config={})), limit=20, stale_days=180, now=NOW
            )
        )
        assert res.connected is True and res.files == []
