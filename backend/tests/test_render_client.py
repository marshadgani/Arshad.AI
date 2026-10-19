"""FEAT-132: Render client parsing, caps and failure codes (no network)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.services.render import client as rc

T = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)

    def _raise():
        if status >= 400:
            raise httpx.HTTPStatusError("x", request=MagicMock(), response=r)

    r.raise_for_status = _raise
    return r


def _client(*responses):
    c = MagicMock()
    c.get = AsyncMock(side_effect=list(responses))
    return c


def _entry(level):
    return {
        "timestamp": "2026-10-19T06:01:00Z",
        "message": "m",
        "labels": [{"name": "level", "value": level}],
    }


@pytest.mark.asyncio
async def test_fetch_logs_keeps_level_per_record():
    c = _client(
        _resp(200, {"logs": [_entry("error"), _entry("info")], "hasMore": False})
    )
    recs, truncated, code = await rc.fetch_logs("srv-a", "tea-1", T, T, "k", c)
    assert [r.level for r in recs] == ["error", "info"]
    assert truncated is False and code is None


@pytest.mark.asyncio
async def test_fetch_logs_caps_and_flags_truncation():
    page = _resp(
        200,
        {
            "logs": [_entry("info")] * 100,
            "hasMore": True,
            "nextStartTime": "2026-10-19T06:02:00Z",
            "nextEndTime": "2026-10-19T07:00:00Z",
        },
    )
    c = _client(*[page] * 5)
    recs, truncated, _ = await rc.fetch_logs(
        "srv-a", "tea-1", T, T, "k", c, max_results=500
    )
    assert len(recs) == 500 and truncated is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [(401, "needs_reauth"), (403, "scope_insufficient"), (500, "fetch_error")],
)
async def test_fetch_logs_failure_codes(status, code):
    recs, _, got = await rc.fetch_logs(
        "srv-a", "tea-1", T, T, "k", _client(_resp(status, {}))
    )
    assert recs == [] and got == code


@pytest.mark.asyncio
async def test_fetch_logs_without_owner_id_reports_owner_unknown():
    c = _client()
    assert (await rc.fetch_logs("srv-a", None, T, T, "k", c))[2] == "owner_unknown"
    c.get.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_metric_mean_and_failure():
    body = [
        {"values": [{"timestamp": "t", "value": 1.0}, {"timestamp": "t", "value": 3.0}]}
    ]
    ok = await rc.fetch_metric("srv-a", T, T, "cpu", "k", _client(_resp(200, body)))
    assert ok.mean == 2.0 and ok.sample_count == 2 and not ok.fetch_failed
    bad = await rc.fetch_metric("srv-a", T, T, "cpu", "k", _client(_resp(403, {})))
    assert bad.fetch_failed and bad.failure_code == "scope_insufficient"


@pytest.mark.asyncio
async def test_deploy_id_is_url_quoted_and_404_is_none():
    c = _client(_resp(404, {}))
    assert await rc.fetch_deploy_record("srv-a", "../x", "k", c) is None
    assert "../x" not in c.get.await_args.args[0]
