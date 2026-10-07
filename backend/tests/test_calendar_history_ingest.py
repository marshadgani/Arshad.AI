"""Unit tests for the calendar ingestion window and paging options.

No database: the tool call and the DB session are faked.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.services.ingestion import calendar as cal
from src.services.ingestion.errors import IngestionError


class _FakeTool:
    pages: list[dict] = []
    calls: list = []

    async def __call__(self, *, user, db, payload):
        type(self).calls.append(payload)
        data = type(self).pages[len(type(self).calls) - 1]
        return SimpleNamespace(data=data)


@pytest.fixture
def tool(monkeypatch):
    _FakeTool.pages = []
    _FakeTool.calls = []
    monkeypatch.setattr(cal, "CalendarListEvents", _FakeTool)
    monkeypatch.setattr(cal.event_bus, "publish", AsyncMock())
    return _FakeTool


def _db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _ev(i):
    return {"id": f"e{i}", "start": {"dateTime": "2024-01-01T10:00:00Z"}}


@pytest.mark.asyncio
async def test_default_run_reads_one_page_and_ignores_next_token(tool):
    tool.pages = [{"items": [_ev(1)], "nextPageToken": "t2"}]
    out = await cal.ingest(user=_user(), db=_db(), payload={})
    assert out == {"ingested_count": 1, "skipped_count": 0, "truncated": False}
    assert len(tool.calls) == 1


@pytest.mark.asyncio
async def test_history_days_widens_window_back_and_ahead(tool):
    tool.pages = [{"items": []}]
    await cal.ingest(user=_user(), db=_db(), payload={"history_days": 1825})
    p = tool.calls[0]
    lo = datetime.fromisoformat(p.time_min)
    hi = datetime.fromisoformat(p.time_max)
    now = datetime.now(timezone.utc)
    assert abs((now - lo) - timedelta(days=1825)) < timedelta(minutes=1)
    assert abs((hi - now) - timedelta(days=365)) < timedelta(minutes=1)


@pytest.mark.asyncio
async def test_history_follows_page_tokens_until_exhausted(tool):
    tool.pages = [
        {"items": [_ev(1), _ev(2)], "nextPageToken": "t2"},
        {"items": [_ev(3)], "nextPageToken": "t3"},
        {"items": [_ev(4)]},
    ]
    out = await cal.ingest(user=_user(), db=_db(), payload={"history_days": 400})
    assert out["ingested_count"] == 4
    assert [c.page_token for c in tool.calls] == [None, "t2", "t3"]


@pytest.mark.asyncio
async def test_history_dedupes_ids_repeated_across_pages(tool):
    tool.pages = [
        {"items": [_ev(1), _ev(2)], "nextPageToken": "t2"},
        {"items": [_ev(2), _ev(3)]},
    ]
    db = _db()
    out = await cal.ingest(user=_user(), db=db, payload={"history_days": 400})
    assert out == {"ingested_count": 3, "skipped_count": 1, "truncated": False}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_stops_at_page_cap(tool, monkeypatch):
    monkeypatch.setattr(cal, "_MAX_HISTORY_PAGES", 2)
    tool.pages = [
        {"items": [_ev(1)], "nextPageToken": "t2"},
        {"items": [_ev(2)], "nextPageToken": "t3"},
        {"items": [_ev(3)]},
    ]
    out = await cal.ingest(user=_user(), db=_db(), payload={"history_days": 400})
    assert out["ingested_count"] == 2
    assert out["truncated"] is True
    assert len(tool.calls) == 2


@pytest.mark.asyncio
async def test_history_days_is_capped_at_ten_years(tool):
    tool.pages = [{"items": []}]
    await cal.ingest(user=_user(), db=_db(), payload={"history_days": 99999})
    lo = datetime.fromisoformat(tool.calls[0].time_min)
    assert datetime.now(timezone.utc) - lo <= timedelta(days=3651)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["abc", 0, -5, [1]])
async def test_invalid_history_days_is_rejected(tool, bad):
    with pytest.raises(IngestionError, match="invalid_history_days"):
        await cal.ingest(user=_user(), db=_db(), payload={"history_days": bad})
    assert tool.calls == []


@pytest.mark.asyncio
async def test_full_refresh_window_is_unchanged_and_reads_one_page(tool):
    tool.pages = [{"items": [_ev(1)], "nextPageToken": "t2"}]
    await cal.ingest(user=_user(), db=_db(), payload={"full_refresh": True})
    p = tool.calls[0]
    now = datetime.now(timezone.utc)
    assert abs((now - datetime.fromisoformat(p.time_min)) - timedelta(days=90)) < timedelta(minutes=1)
    assert abs((datetime.fromisoformat(p.time_max) - now) - timedelta(days=365)) < timedelta(minutes=1)
    assert len(tool.calls) == 1


@pytest.mark.asyncio
async def test_history_days_takes_precedence_over_full_refresh(tool):
    tool.pages = [{"items": []}]
    await cal.ingest(
        user=_user(), db=_db(), payload={"history_days": 1000, "full_refresh": True}
    )
    lo = datetime.fromisoformat(tool.calls[0].time_min)
    assert datetime.now(timezone.utc) - lo > timedelta(days=900)


@pytest.mark.asyncio
async def test_missing_id_events_are_skipped_and_counted(tool):
    tool.pages = [{"items": [_ev(1), {"start": {"date": "2024-01-01"}}]}]
    out = await cal.ingest(user=_user(), db=_db(), payload={})
    assert out["ingested_count"] == 1
    assert out["skipped_count"] == 1


@pytest.mark.asyncio
async def test_large_history_is_inserted_in_chunks(tool, monkeypatch):
    monkeypatch.setattr(cal, "_INSERT_CHUNK", 2)
    tool.pages = [{"items": [_ev(i) for i in range(5)]}]
    db = _db()
    out = await cal.ingest(user=_user(), db=db, payload={"history_days": 400})
    assert out["ingested_count"] == 5
    assert db.execute.await_count == 3
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_last_copy_of_a_repeated_id_wins(tool):
    first = {"id": "e1", "summary": "old", "start": {"dateTime": "2024-01-01T10:00:00Z"}}
    last = {"id": "e1", "summary": "new", "start": {"dateTime": "2024-01-01T10:00:00Z"}}
    tool.pages = [{"items": [first], "nextPageToken": "t2"}, {"items": [last]}]
    db = _db()
    await cal.ingest(user=_user(), db=db, payload={"history_days": 400})
    values = db.execute.await_args.args[0].compile().params
    assert "new" in str(values) and "old" not in str(values)


@pytest.mark.asyncio
async def test_tool_sends_page_token_only_when_set(monkeypatch):
    from src.tools.calendar import list_events as le

    sent = []

    async def fake_request(**kw):
        sent.append(kw["params"])
        return {"items": []}

    monkeypatch.setattr(le.google_calendar, "request", fake_request)
    tool = le.CalendarListEvents()
    base = dict(time_min="2024-01-01T00:00:00Z", time_max="2024-02-01T00:00:00Z")
    await tool(user=_user(), db=_db(), payload=le.ListEventsInput(**base))
    await tool(user=_user(), db=_db(), payload=le.ListEventsInput(**base, page_token="abc"))
    assert "pageToken" not in sent[0]
    assert sent[1]["pageToken"] == "abc"
