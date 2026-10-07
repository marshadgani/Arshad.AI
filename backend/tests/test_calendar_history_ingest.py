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
    assert out == {"ingested_count": 1, "skipped_count": 0}
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
    assert out == {"ingested_count": 3, "skipped_count": 1}
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
