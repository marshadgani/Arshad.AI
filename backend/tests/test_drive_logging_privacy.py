"""NF-201: Drive logs must never contain file names, IDs tied to names,
permission email addresses, tokens, or Drive URLs.

All scenarios run through the full service layer with sentinel values
that would be immediately spotted in logs if leaked.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from src.services.drive import DriveAuditService
from src.services.google_token import TokenUnavailableError

SENTINEL_NAME = "SENTINEL-FILE-NAME-DO-NOT-LOG-abc123xyz.pdf"
SENTINEL_EMAIL = "sentinel-email-abc123xyz@privacy-test.invalid"
SENTINEL_ID = "sentinel-drive-id-abc123xyz"
SENTINEL_TOKEN = "sentinel-access-token-abc123xyz"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
USER_ID = uuid.uuid4()


def _integration(status="connected"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="google_drive",
        status=status,
        config={},
        last_error=None,
    )


class _DB:
    def __init__(self, intg):
        self._intg = intg

    async def execute(self, stmt):
        class _R:
            def __init__(self, row):
                self._row = row

            def scalar_one_or_none(self):
                return self._row

        return _R(self._intg)

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _patch_token(monkeypatch, raises=None):
    import src.services.drive._errors as mod

    if raises is not None:

        async def _t(uid, db):
            raise raises
    else:

        async def _t(uid, db):
            return SENTINEL_TOKEN

    monkeypatch.setattr(mod, "get_valid_google_token", _t)


def _sentinel_drive_files():
    return [
        {
            "id": SENTINEL_ID,
            "name": SENTINEL_NAME,
            "modifiedTime": "2025-01-01T00:00:00Z",
            "webViewLink": f"https://drive.google.com/file/d/{SENTINEL_ID}",
            "permissions": [
                {"type": "user", "role": "reader", "emailAddress": SENTINEL_EMAIL}
            ],
        }
    ]


def _patch_http(monkeypatch, raises=None):
    import src.services.drive.service as mod

    if raises is not None:

        async def _l(token, *, limit, **kw):
            raise raises
    else:

        async def _l(token, *, limit, **kw):
            return _sentinel_drive_files(), False

    monkeypatch.setattr(mod, "list_recent_files", _l)


def run(coro):
    return asyncio.run(coro)


def _no_sentinel_in_logs(records):
    """Assert none of the sentinel strings appear in any log record."""
    for record in records:
        text = record.getMessage()
        exc_text = record.exc_text or ""
        for sentinel in (SENTINEL_NAME, SENTINEL_EMAIL, SENTINEL_ID, SENTINEL_TOKEN):
            assert sentinel not in text, (
                f"Sentinel '{sentinel}' leaked into log: {text!r}"
            )
            assert sentinel not in exc_text, (
                f"Sentinel '{sentinel}' leaked into exc_text: {exc_text!r}"
            )


@pytest.fixture
def caplog_all(caplog):
    with caplog.at_level(logging.DEBUG, logger="src.services.drive"):
        yield caplog


class TestLoggingPrivacy:
    def test_happy_path_no_sentinel_in_logs(self, monkeypatch, caplog_all):
        _patch_token(monkeypatch)
        _patch_http(monkeypatch)
        intg = _integration()
        run(
            DriveAuditService.get_audit_results(
                USER_ID, _DB(intg), limit=20, stale_days=180, now=NOW
            )
        )
        _no_sentinel_in_logs(caplog_all.records)

    def test_google_403_no_sentinel_in_logs(self, monkeypatch, caplog_all):
        _patch_token(monkeypatch)
        resp = httpx.Response(
            403, json={"error": "forbidden", "details": SENTINEL_NAME}
        )
        exc = httpx.HTTPStatusError(
            SENTINEL_NAME, request=httpx.Request("GET", "https://drive"), response=resp
        )
        _patch_http(monkeypatch, raises=exc)
        intg = _integration()
        run(
            DriveAuditService.get_audit_results(
                USER_ID, _DB(intg), limit=20, stale_days=180, now=NOW
            )
        )
        _no_sentinel_in_logs(caplog_all.records)

    def test_network_timeout_no_sentinel_in_logs(self, monkeypatch, caplog_all):
        _patch_token(monkeypatch)
        _patch_http(monkeypatch, raises=httpx.ConnectTimeout(SENTINEL_NAME))
        intg = _integration()
        run(
            DriveAuditService.get_audit_results(
                USER_ID, _DB(intg), limit=20, stale_days=180, now=NOW
            )
        )
        _no_sentinel_in_logs(caplog_all.records)

    def test_token_unavailable_no_sentinel_in_logs(self, monkeypatch, caplog_all):
        _patch_token(monkeypatch, raises=TokenUnavailableError(SENTINEL_NAME))
        intg = _integration()
        run(
            DriveAuditService.get_audit_results(
                USER_ID, _DB(intg), limit=20, stale_days=180, now=NOW
            )
        )
        _no_sentinel_in_logs(caplog_all.records)

    def test_truncation_log_is_counts_only(self, monkeypatch, caplog_all):
        """Truncation warning must contain only numeric counts, no names."""
        _patch_token(monkeypatch)
        import src.services.drive.service as mod

        async def _trunc(token, *, limit, **kw):
            return _sentinel_drive_files(), True  # truncated=True

        monkeypatch.setattr(mod, "list_recent_files", _trunc)
        intg = _integration()
        run(
            DriveAuditService.get_audit_results(
                USER_ID, _DB(intg), limit=20, stale_days=180, now=NOW
            )
        )
        _no_sentinel_in_logs(caplog_all.records)

    def test_knowledge_suggestions_no_sentinel_in_logs(self, monkeypatch, caplog_all):
        intg = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=USER_ID,
            slug="google_drive",
            status="connected",
            config={"files": [{"id": SENTINEL_ID, "name": SENTINEL_NAME}]},
            last_error=None,
        )
        run(DriveAuditService.get_knowledge_suggestions(USER_ID, _DB(intg)))
        _no_sentinel_in_logs(caplog_all.records)

    def test_log_records_contain_only_type_or_status(self, monkeypatch, caplog_all):
        """Warning logs must use only exception class name or HTTP status."""
        _patch_token(monkeypatch)
        resp = httpx.Response(500, json={})
        exc = httpx.HTTPStatusError(
            "internal", request=httpx.Request("GET", "https://drive"), response=resp
        )
        _patch_http(monkeypatch, raises=exc)
        intg = _integration()
        run(
            DriveAuditService.get_audit_results(
                USER_ID, _DB(intg), limit=20, stale_days=180, now=NOW
            )
        )
        warning_records = [
            r for r in caplog_all.records if r.levelno >= logging.WARNING
        ]
        for rec in warning_records:
            msg = rec.getMessage()
            assert (
                "HTTPStatusError" in msg
                or "500" in msg
                or "ConnectTimeout" in msg
                or "status=" in msg
                or "fetch_failed" in msg
                or "rate_limited" in msg
                or "forbidden" in msg
            ), f"Log message uses unexpected format: {msg!r}"
