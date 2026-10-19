"""Integration tests for DriveAuditService orchestration.

All I/O is mocked. Tests verify integration-status transitions,
token error handling, user-scoping (NF-208), and the always-200 contract.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
from src.services.drive import DriveAuditService
from src.services.google_token import TokenUnavailableError

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


def _integration(user_id=None, status="connected", config=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or USER_A,
        slug="google_drive",
        status=status,
        config=config or {},
        last_error=None,
    )


class _ScopedDB:
    """Returns integration only for the correct user_id (NF-208 guard)."""

    def __init__(self, integration=None, user_id=None):
        self._intg = integration
        self._uid = user_id or (integration.user_id if integration else None)
        self.committed = 0
        self.executed_user_ids = []

    async def execute(self, stmt):
        try:
            params = list(stmt.compile().params.values())
            self.executed_user_ids.extend(p for p in params if isinstance(p, uuid.UUID))
        except Exception:
            pass

        class _Result:
            def __init__(self, row):
                self._row = row

            def scalar_one_or_none(self):
                return self._row

        return _Result(self._intg)

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        pass


def _patch_token(monkeypatch, token="fake-token", raises=None):
    import src.services.drive._errors as mod

    if raises is not None:

        async def _get(uid, db):
            raise raises

        monkeypatch.setattr(mod, "get_valid_google_token", _get)
    else:

        async def _get(uid, db):
            return token

        monkeypatch.setattr(mod, "get_valid_google_token", _get)


def _patch_http(monkeypatch, files=None, truncated=False, raises=None):
    import src.services.drive.service as mod

    if raises is not None:

        async def _list(token, *, limit, **kw):
            raise raises

        monkeypatch.setattr(mod, "list_recent_files", _list)
    else:

        async def _list(token, *, limit, **kw):
            return (files or []), truncated

        monkeypatch.setattr(mod, "list_recent_files", _list)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Integration not found / disconnected
# ---------------------------------------------------------------------------


class TestNoIntegration:
    def test_no_integration_returns_not_connected(self, monkeypatch):
        db = _ScopedDB(integration=None)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.connected is False
        assert result.needs_reauth is False
        assert result.files == []

    def test_no_integration_no_token_call(self, monkeypatch):
        called = []
        import src.services.drive._errors as mod

        async def _sentinel(*a, **kw):
            called.append(1)
            return "t"

        monkeypatch.setattr(mod, "get_valid_google_token", _sentinel)
        db = _ScopedDB(integration=None)
        run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert called == []


# ---------------------------------------------------------------------------
# NF-207 — TokenUnavailableError
# ---------------------------------------------------------------------------


class TestTokenErrors:
    def test_token_unavailable_returns_needs_reauth(self, monkeypatch):
        _patch_token(monkeypatch, raises=TokenUnavailableError("no token"))
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.connected is True
        assert result.needs_reauth is True
        assert "google_drive: needs_reauth" in result.partial_failures

    def test_token_refresh_400_raises_token_unavailable(self, monkeypatch):
        """HTTPStatusError 400-403 on refresh maps to TokenUnavailableError."""
        resp = httpx.Response(400, json={"error": "invalid_grant"})
        exc = httpx.HTTPStatusError(
            "bad", request=httpx.Request("POST", "https://oauth"), response=resp
        )
        _patch_token(monkeypatch, raises=exc)
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.needs_reauth is True


# ---------------------------------------------------------------------------
# NF-206 — Drive HTTP errors
# ---------------------------------------------------------------------------


class TestDriveHttpErrors:
    def _drive_exc(self, status):
        resp = httpx.Response(status, json={"error": "err"})
        return httpx.HTTPStatusError(
            "Drive error", request=httpx.Request("GET", "https://drive"), response=resp
        )

    def test_drive_401_returns_needs_reauth(self, monkeypatch):
        _patch_token(monkeypatch)
        _patch_http(monkeypatch, raises=self._drive_exc(401))
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.needs_reauth is True
        assert result.connected is True

    def test_drive_403_asks_for_a_reconnect_like_the_sync_does(self, monkeypatch):
        """403 = the drive.metadata.readonly scope was never granted."""
        _patch_token(monkeypatch)
        _patch_http(monkeypatch, raises=self._drive_exc(403))
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.needs_reauth is True
        assert intg.status == "expired"

    def test_drive_500_returns_partial_failure(self, monkeypatch):
        _patch_token(monkeypatch)
        _patch_http(monkeypatch, raises=self._drive_exc(500))
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.connected is True
        assert result.needs_reauth is False
        assert result.partial_failures

    def test_network_error_returns_partial_failure(self, monkeypatch):
        _patch_token(monkeypatch)
        _patch_http(monkeypatch, raises=httpx.ConnectTimeout("timeout"))
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.connected is True
        assert "network_error" in str(result.partial_failures)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_happy_path_returns_classified_files(self, monkeypatch):
        _patch_token(monkeypatch)
        files = [
            {
                "id": "f1",
                "name": "A.pdf",
                "modifiedTime": (NOW - timedelta(days=300)).isoformat(),
                "webViewLink": "https://drive.google.com/f1",
                "permissions": [{"type": "anyone", "role": "reader"}],
            },
        ]
        _patch_http(monkeypatch, files=files)
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.connected is True
        assert result.total == 1
        assert result.files[0].anyone_with_link is True

    def test_truncated_flag_forwarded(self, monkeypatch):
        _patch_token(monkeypatch)
        _patch_http(monkeypatch, files=[], truncated=True)
        intg = _integration()
        db = _ScopedDB(integration=intg)
        result = run(
            DriveAuditService.get_audit_results(
                USER_A, db, limit=20, stale_days=180, now=NOW
            )
        )
        assert result.truncated is True


# ---------------------------------------------------------------------------
# NF-208 — per-user scoping
# ---------------------------------------------------------------------------


class TestUserScoping:
    def test_user_b_integration_not_read_in_user_a_call(self, monkeypatch):
        """Two calls with different user IDs must each use their own integration."""
        _patch_token(monkeypatch)
        _patch_http(monkeypatch)
        intg_a = _integration(user_id=USER_A, status="connected")
        intg_b = _integration(user_id=USER_B, status="connected")

        class _PerUserDB:
            def __init__(self, user_id, intg):
                self._uid = user_id
                self._intg = intg
                self.queried_ids: list[uuid.UUID] = []

            async def execute(self, stmt):
                class _R:
                    def __init__(self, row):
                        self._r = row

                    def scalar_one_or_none(self):
                        return self._r

                return _R(self._intg)

            async def commit(self):
                pass

            async def rollback(self):
                pass

        db_a = _PerUserDB(USER_A, intg_a)
        db_b = _PerUserDB(USER_B, intg_b)
        res_a = run(
            DriveAuditService.get_audit_results(
                USER_A, db_a, limit=20, stale_days=180, now=NOW
            )
        )
        res_b = run(
            DriveAuditService.get_audit_results(
                USER_B, db_b, limit=20, stale_days=180, now=NOW
            )
        )
        assert res_a.connected is True
        assert res_b.connected is True


# ---------------------------------------------------------------------------
# get_knowledge_suggestions — no live Drive call (NF-105 / cache-only)
# ---------------------------------------------------------------------------


class TestKnowledgeSuggestionsNoDriveCall:
    def test_no_http_call_made(self, monkeypatch):
        called = []

        async def _list(*a, **kw):
            called.append(1)

        import src.services.drive.service as mod

        monkeypatch.setattr(mod, "list_recent_files", _list)

        intg = _integration(
            user_id=USER_A, config={"files": [{"id": "f1", "name": "a.pdf"}]}
        )

        class _DB:
            async def execute(self, stmt):
                class _R:
                    def scalar_one_or_none(self):
                        return intg

                return _R()

            async def commit(self):
                pass

        run(DriveAuditService.get_knowledge_suggestions(USER_A, _DB()))
        assert called == [], "get_knowledge_suggestions must not call list_recent_files"

    def test_expired_integration_returns_needs_reauth(self):
        intg = _integration(
            user_id=USER_A,
            status="expired",
            config={"files": [{"id": "f1", "name": "a.pdf"}]},
        )

        class _DB:
            async def execute(self, stmt):
                class _R:
                    def scalar_one_or_none(self):
                        return intg

                return _R()

            async def commit(self):
                pass

        result = run(DriveAuditService.get_knowledge_suggestions(USER_A, _DB()))
        assert result.needs_reauth is True
        assert result.connected is True
        assert result.names == []
