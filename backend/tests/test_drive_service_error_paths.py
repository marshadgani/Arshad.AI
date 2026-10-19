"""Service and HTTP-layer error-path tests for FEAT-123 Drive audit.

Fills gaps left by the original suite: persisted integration state on
errors, partial_failure labels, swallowed commit/mark_healthy failures,
knowledge-suggestion cache edge cases, and a working httpx MockTransport
harness for list_recent_files.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import src.services.drive._errors as errors_mod
import src.services.drive._http as http_mod
import src.services.drive.service as svc_mod
from src.services.drive import DriveAuditService
from src.services.drive._classify import classify_files
from src.services.drive._constants import _PAGE_CAP

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
        config=config if config is not None else {},
        last_error=None,
    )


class _DB:
    def __init__(self, intg, fail_commit=False):
        self._intg = intg
        self.fail_commit = fail_commit
        self.rollbacks = 0

    async def execute(self, stmt):
        row = self._intg

        class _R:
            def scalar_one_or_none(self):
                return row

        return _R()

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("db down")

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def healthy(monkeypatch):
    calls = []

    async def _mark(integration, db):
        calls.append(integration)

    monkeypatch.setattr(svc_mod, "mark_healthy", _mark)

    async def _tok(uid, db):
        return "tok"

    monkeypatch.setattr(errors_mod, "get_valid_google_token", _tok)
    return calls


def _http_error(status):
    resp = httpx.Response(status, json={"error": "x"})
    return httpx.HTTPStatusError(
        "boom", request=httpx.Request("GET", "https://drive"), response=resp
    )


def _patch_list(monkeypatch, files=None, truncated=False, raises=None, seen=None):
    async def _list(token, *, limit, **kw):
        if seen is not None:
            seen["limit"] = limit
        if raises is not None:
            raise raises
        return (files or []), truncated

    monkeypatch.setattr(svc_mod, "list_recent_files", _list)


def _audit(db):
    return run(
        DriveAuditService.get_audit_results(USER, db, limit=20, stale_days=180, now=NOW)
    )


class TestPersistedStateOnErrors:
    def test_drive_401_marks_integration_expired_with_sanitised_error(
        self, monkeypatch, healthy
    ):
        _patch_list(monkeypatch, raises=_http_error(401))
        intg = _intg()
        res = _audit(_DB(intg))
        assert res.needs_reauth is True
        assert intg.status == "expired"
        assert intg.last_error == "HTTPStatusError: status=401"

    def test_drive_429_is_rate_limited_and_marks_error_not_expired(
        self, monkeypatch, healthy
    ):
        _patch_list(monkeypatch, raises=_http_error(429))
        intg = _intg()
        res = _audit(_DB(intg))
        assert res.partial_failures == ["google_drive: rate_limited"]
        assert res.needs_reauth is False
        assert intg.status == "error"

    def test_drive_403_asks_for_a_reconnect(self, monkeypatch, healthy):
        _patch_list(monkeypatch, raises=_http_error(403))
        intg = _intg()
        res = _audit(_DB(intg))
        assert res.needs_reauth is True
        assert res.partial_failures == ["google_drive: needs_reauth"]
        assert intg.status == "expired"

    def test_unexpected_exception_labelled_and_sanitised(self, monkeypatch, healthy):
        _patch_list(monkeypatch, raises=ValueError("SECRET-NAME.pdf"))
        intg = _intg()
        res = _audit(_DB(intg))
        assert res.partial_failures == ["google_drive: unexpected_error"]
        assert intg.last_error == "ValueError"
        assert "SECRET" not in intg.last_error

    def test_token_refresh_500_is_fetch_failed_not_reauth(self, monkeypatch):
        async def _tok(uid, db):
            raise _http_error(500)

        monkeypatch.setattr(errors_mod, "get_valid_google_token", _tok)
        intg = _intg()
        res = _audit(_DB(intg))
        assert res.needs_reauth is False
        assert res.partial_failures == ["google_drive: fetch_failed"]
        assert intg.status == "error"


class TestSuccessPath:
    def test_success_calls_mark_healthy(self, monkeypatch, healthy):
        _patch_list(monkeypatch, files=[])
        _audit(_DB(_intg(status="error")))
        assert len(healthy) == 1

    def test_mark_healthy_failure_does_not_break_response(self, monkeypatch, healthy):
        async def _boom(integration, db):
            raise RuntimeError("x")

        monkeypatch.setattr(svc_mod, "mark_healthy", _boom)
        _patch_list(monkeypatch, files=[{"id": "f1", "name": "a"}])
        res = _audit(_DB(_intg()))
        assert res.total == 1 and res.partial_failures == []

    def test_commit_failure_triggers_rollback_and_still_returns(
        self, monkeypatch, healthy
    ):
        _patch_list(monkeypatch, files=[])
        db = _DB(_intg(), fail_commit=True)
        res = _audit(db)
        assert res.connected is True
        assert db.rollbacks >= 1

    def test_limit_forwarded_to_http_layer(self, monkeypatch, healthy):
        seen = {}
        _patch_list(monkeypatch, seen=seen)
        run(
            DriveAuditService.get_audit_results(
                USER, _DB(_intg()), limit=7, stale_days=180, now=NOW
            )
        )
        assert seen["limit"] == 7

    def test_entries_without_id_reported_as_unreadable(self, monkeypatch, healthy):
        files = [{"id": "f1", "name": "ok"}, {"name": "no-id"}, "junk"]
        _patch_list(monkeypatch, files=files)
        res = _audit(_DB(_intg()))
        assert res.total == 1
        assert res.partial_failures == ["google_drive: unreadable_entries"]


class TestKnowledgeCacheEdges:
    def _run(self, intg):
        return run(DriveAuditService.get_knowledge_suggestions(USER, _DB(intg)))

    def test_error_status_surfaces_sync_error_but_keeps_names(self):
        r = self._run(
            _intg(status="error", config={"files": [{"id": "1", "name": "a.pdf"}]})
        )
        assert r.names == ["a.pdf"]
        assert "google_drive: sync_error" in r.partial_failures

    def test_files_not_a_list_reports_cache_unreadable(self):
        r = self._run(_intg(config={"files": "oops"}))
        assert r.names == []
        assert "google_drive: cache_unreadable" in r.partial_failures

    def test_config_not_a_dict_reports_cache_unreadable(self):
        r = self._run(_intg(config=["x"]))
        assert r.names == []
        assert "google_drive: cache_unreadable" in r.partial_failures

    def test_recency_order_preserved_after_dedup(self):
        files = [{"id": str(i), "name": n} for i, n in enumerate(["b", "a", "b", "c"])]
        r = self._run(_intg(config={"files": files}))
        assert r.names == ["b", "a", "c"]

    def test_no_integration_is_honest_empty_state(self):
        r = run(DriveAuditService.get_knowledge_suggestions(USER, _DB(None)))
        assert (r.connected, r.names, r.total) == (False, [], 0)


class TestClassifyEdges:
    def _f(self, **kw):
        base = {
            "id": "f",
            "name": "n",
            "modifiedTime": "2020-01-01T00:00:00Z",
            "permissions": [
                {"type": "user", "role": "owner"},
                {"type": "user", "role": "writer"},
            ],
        }
        base.update(kw)
        return base

    def test_owner_plus_writer_old_file_is_stale(self):
        assert (
            classify_files([self._f()], now=NOW, stale_days=180)[0].stale_sharing
            is True
        )

    def test_unparseable_modified_time_is_unknown_not_false(self):
        r = classify_files(
            [self._f(modifiedTime="NOT-A-DATE")], now=NOW, stale_days=180
        )[0]
        assert r.stale_sharing is None

    def test_missing_modified_time_is_unknown_not_false(self):
        f = self._f()
        del f["modifiedTime"]
        assert classify_files([f], now=NOW, stale_days=180)[0].stale_sharing is None

    def test_unparseable_time_still_reports_public_link(self):
        f = self._f(
            modifiedTime="bad", permissions=[{"type": "anyone", "role": "reader"}]
        )
        assert classify_files([f], now=NOW, stale_days=180)[0].anyone_with_link is True

    def test_naive_now_treated_as_utc(self):
        naive = datetime(2026, 1, 1)
        assert (
            classify_files([self._f()], now=naive, stale_days=180)[0].stale_sharing
            is True
        )


def _client_factory(handler):
    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    return lambda **kw: real(transport=transport)


class TestListRecentFilesHarness:
    def _call(self, monkeypatch, pages, limit=20, page_cap=_PAGE_CAP):
        queue = list(pages)
        requests = []

        async def handler(request):
            requests.append(request)
            return queue.pop(0) if queue else httpx.Response(500)

        monkeypatch.setattr(http_mod.httpx, "AsyncClient", _client_factory(handler))
        out = run(http_mod.list_recent_files("TOK", limit=limit, page_cap=page_cap))
        return out, requests

    @staticmethod
    def _page(n, token=None):
        body = {"files": [{"id": f"f{i}"} for i in range(n)]}
        if token:
            body["nextPageToken"] = token
        return httpx.Response(200, json=body)

    def test_more_files_than_limit_sliced_and_truncated(self, monkeypatch):
        (files, truncated), _ = self._call(monkeypatch, [self._page(10)], limit=5)
        assert len(files) == 5 and truncated is True

    def test_page_cap_enforced_and_reports_truncation(self, monkeypatch):
        pages = [self._page(1, f"t{i}") for i in range(10)]
        (files, truncated), reqs = self._call(monkeypatch, pages, limit=100, page_cap=3)
        assert len(reqs) == 3 and truncated is True

    def test_page_token_sent_on_second_request(self, monkeypatch):
        _, reqs = self._call(
            monkeypatch, [self._page(1, "NEXT"), self._page(1)], limit=100
        )
        assert reqs[1].url.params["pageToken"] == "NEXT"

    def test_only_get_with_bearer_and_bounded_page_size(self, monkeypatch):
        _, reqs = self._call(monkeypatch, [self._page(0)], limit=500)
        assert all(r.method == "GET" for r in reqs)
        assert reqs[0].headers["authorization"] == "Bearer TOK"
        assert int(reqs[0].url.params["pageSize"]) <= 100

    @pytest.mark.parametrize("status", [401, 403, 429, 500])
    def test_error_status_raises(self, monkeypatch, status):
        with pytest.raises(httpx.HTTPStatusError):
            self._call(monkeypatch, [httpx.Response(status)])
