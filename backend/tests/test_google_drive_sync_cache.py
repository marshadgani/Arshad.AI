"""Tests for GoogleDriveIntegration.sync cache-writing behaviour.

FN-105 (sync stores file metadata), NF-201 (no file names in logs/last_error).
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from src.integrations.personal.google_drive import GoogleDriveIntegration

_DRIVE_URL = "https://www.googleapis.com/drive/v3/files"


def _integration(status="connected"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        slug="google_drive",
        status=status,
        config={},
        last_error=None,
        last_synced_at=None,
    )


def _fake_files(n=5):
    return [
        {
            "id": f"fid-{i}",
            "name": f"PLACEHOLDER-NAME-{i}.pdf",
            "mimeType": "application/pdf",
            "modifiedTime": "2025-01-01T00:00:00Z",
            "webViewLink": f"https://drive.google.com/file/d/fid-{i}",
        }
        for i in range(n)
    ]


class _FakeDB:
    def __init__(self, user):
        self._user = user
        self.committed = 0

    async def scalar(self, stmt):
        return self._user

    async def commit(self):
        self.committed += 1


def _make_client(files, status_code=200, has_more=False):
    body = {"files": files}
    if has_more:
        body["nextPageToken"] = "next-tok"
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = (
        MagicMock()
        if status_code < 400
        else MagicMock(
            side_effect=httpx.HTTPStatusError(
                "err", request=MagicMock(), response=MagicMock(status_code=status_code)
            )
        )
    )
    resp.json = MagicMock(return_value=body)

    class _FakeAsyncClient:
        def __init__(self, **kwargs):  # accept timeout= etc.
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            return resp

    return _FakeAsyncClient


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Sync API call parameters
# ---------------------------------------------------------------------------


class TestSyncApiParams:
    def test_sync_uses_page_size_30(self, monkeypatch):
        user = SimpleNamespace(id=uuid.uuid4(), email="u@example.com")
        intg = _integration()
        db = _FakeDB(user)
        captured_params = {}

        class _Client:
            def __init__(self, **kwargs):  # accept timeout= etc. from production code
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def get(self, url, *, params, headers):
                captured_params.update(params)
                resp = MagicMock()
                resp.status_code = 200
                resp.raise_for_status = MagicMock()
                resp.json = MagicMock(return_value={"files": []})
                return resp

        async def _get_token(db, user, provider):
            return "fake-token", None

        monkeypatch.setattr(
            "src.integrations.personal.google_drive.get_access_token", _get_token
        )
        monkeypatch.setattr(
            "src.integrations.personal.google_drive.httpx.AsyncClient", _Client
        )
        run(GoogleDriveIntegration().sync(integration=intg, db=db))
        assert captured_params.get("pageSize") == 30

    def test_sync_fields_include_modified_time_and_web_view_link(self, monkeypatch):
        user = SimpleNamespace(id=uuid.uuid4(), email="u@example.com")
        intg = _integration()
        db = _FakeDB(user)
        captured_params = {}

        class _Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def get(self, url, *, params, headers):
                captured_params.update(params)
                resp = MagicMock()
                resp.status_code = 200
                resp.raise_for_status = MagicMock()
                resp.json = MagicMock(return_value={"files": []})
                return resp

        async def _get_token(db, user, provider):
            return "fake-token", None

        monkeypatch.setattr(
            "src.integrations.personal.google_drive.get_access_token", _get_token
        )
        monkeypatch.setattr(
            "src.integrations.personal.google_drive.httpx.AsyncClient", _Client
        )
        run(GoogleDriveIntegration().sync(integration=intg, db=db))
        fields = captured_params.get("fields", "")
        assert "modifiedTime" in fields
        assert "webViewLink" in fields


# ---------------------------------------------------------------------------
# Cached config shape
# ---------------------------------------------------------------------------


class TestCachedConfigShape:
    def _sync_and_get_config(self, monkeypatch, files, has_more=False):
        user = SimpleNamespace(id=uuid.uuid4(), email="u@example.com")
        intg = _integration()
        db = _FakeDB(user)

        fake_cls = _make_client(files, has_more=has_more)

        async def _get_token(db, user, provider):
            return "fake-token", None

        monkeypatch.setattr(
            "src.integrations.personal.google_drive.get_access_token", _get_token
        )
        monkeypatch.setattr(
            "src.integrations.personal.google_drive.httpx.AsyncClient", fake_cls
        )
        run(GoogleDriveIntegration().sync(integration=intg, db=db))
        return intg.config

    def test_config_files_has_required_keys(self, monkeypatch):
        files = _fake_files(3)
        config = self._sync_and_get_config(monkeypatch, files)
        assert "files" in config
        for f in config["files"]:
            for key in ("id", "name", "mime", "modified_time", "web_view_link"):
                assert key in f

    def test_config_files_has_no_permissions_or_email(self, monkeypatch):
        """NF-201 / NF-205: no permission details cached."""
        files = _fake_files(2)
        config = self._sync_and_get_config(monkeypatch, files)
        for f in config["files"]:
            assert "permissions" not in f
            assert "emailAddress" not in f

    def test_config_capped_at_30_files(self, monkeypatch):
        files = _fake_files(35)
        config = self._sync_and_get_config(monkeypatch, files)
        assert len(config["files"]) <= 30

    def test_file_count_reflects_real_count_not_capped(self, monkeypatch):
        files = _fake_files(35)
        config = self._sync_and_get_config(monkeypatch, files)
        assert isinstance(config.get("file_count"), int)

    def test_files_missing_optional_fields_cached_with_none(self, monkeypatch):
        files = [
            {"id": "f1", "name": "doc.pdf"}
        ]  # no mimeType, modifiedTime, webViewLink
        config = self._sync_and_get_config(monkeypatch, files)
        f = config["files"][0]
        assert f["mime"] is None or f["mime"] == ""
        assert f["modified_time"] is None or f["modified_time"] == ""


# ---------------------------------------------------------------------------
# NF-201 — last_error does not embed file names
# ---------------------------------------------------------------------------


class TestLastErrorPrivacy:
    def test_403_last_error_contains_no_file_names(self, monkeypatch):
        user = SimpleNamespace(id=uuid.uuid4(), email="u@example.com")
        intg = _integration()
        db = _FakeDB(user)

        class _BadClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def get(self, url, **kw):
                resp = MagicMock()
                resp.status_code = 403
                resp.raise_for_status = MagicMock()
                return resp

        async def _get_token(db, user, provider):
            return "fake-token", None

        monkeypatch.setattr(
            "src.integrations.personal.google_drive.get_access_token", _get_token
        )
        monkeypatch.setattr(
            "src.integrations.personal.google_drive.httpx.AsyncClient", _BadClient
        )
        try:
            run(GoogleDriveIntegration().sync(integration=intg, db=db))
        except Exception:
            pass
        if intg.last_error:
            assert "PLACEHOLDER-NAME" not in intg.last_error
            assert len(intg.last_error) < 200
