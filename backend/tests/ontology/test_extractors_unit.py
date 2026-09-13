"""Unit tests — extractor pure-function contracts.

All extractors are called with a faked AsyncSession (no DB I/O)
and plain-dict payloads. The pattern uses a minimal async stub for
db.scalars() so tests remain DB-free while exercising extractor logic.

Covers TC-004 through TC-010.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.models.user import User
from src.services.ingestion.ontology.config import OntologyConfig
from src.services.ingestion.ontology.extract.calendar import extract as cal_extract
from src.services.ingestion.ontology.identity import person_id_from_email


def _make_user() -> User:
    u = User()
    u.id = uuid.uuid4()
    u.email = "arshad@example.com"
    return u


def _make_cfg(**kwargs) -> OntologyConfig:
    defaults = {"lookback_days": 90, "max_entities": 2000, "domains": ["calendar"]}
    defaults.update(kwargs)
    return OntologyConfig(**defaults)


def _fake_event_row(
    provider_id: str,
    occurred_at: datetime,
    attendees: list[dict[str, str]] | None = None,
    summary: str = "Team Standup",
) -> MagicMock:
    raw: dict[str, Any] = {"summary": summary, "htmlLink": "https://cal.example"}
    if attendees is not None:
        raw["attendees"] = attendees
    row = MagicMock()
    row.provider_id = provider_id
    row.occurred_at = occurred_at
    row.raw = raw
    row.user_id = uuid.uuid4()
    return row


def _db_stub(rows: list[Any]) -> AsyncMock:
    """Returns a minimal AsyncSession stub whose scalars() returns rows."""
    scalar_result = MagicMock()
    scalar_result.__iter__ = lambda s: iter(rows)
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=scalar_result)
    return db


# ── TC-004 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cal_extract_returns_event_and_person_records():
    user = _make_user()
    now = datetime.now(timezone.utc)
    row = _fake_event_row(
        "evt_001",
        now,
        attendees=[{"email": "alice@example.com", "displayName": "Alice"}],
    )
    db = _db_stub([row])
    cfg = _make_cfg()
    entities = await cal_extract(user, db, cfg)

    types = [e.entity_type for e in entities]
    assert "Event" in types
    assert "Person" in types


# ── TC-005 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cal_extract_dedupes_attendees_within_call():
    """Same email appearing in two events should yield one Person record."""
    user = _make_user()
    now = datetime.now(timezone.utc)
    att = [{"email": "alice@example.com", "displayName": "Alice"}]
    rows = [
        _fake_event_row("evt_001", now, attendees=att),
        _fake_event_row("evt_002", now, attendees=att),
    ]
    db = _db_stub(rows)
    cfg = _make_cfg()
    entities = await cal_extract(user, db, cfg)

    person_records = [e for e in entities if e.entity_type == "Person"]
    assert len(person_records) == 1


# ── TC-006 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cal_extract_handles_missing_attendees_gracefully():
    """A raw payload with no attendees key must not raise; event still emitted."""
    user = _make_user()
    now = datetime.now(timezone.utc)
    row = _fake_event_row("evt_003", now, attendees=None)
    db = _db_stub([row])
    cfg = _make_cfg()
    entities = await cal_extract(user, db, cfg)

    event_records = [e for e in entities if e.entity_type == "Event"]
    assert len(event_records) == 1
    # No person records either — not a crash
    person_records = [e for e in entities if e.entity_type == "Person"]
    assert len(person_records) == 0


# ── TC-007 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cal_extract_relationships_link_event_to_person():
    user = _make_user()
    now = datetime.now(timezone.utc)
    email = "bob@example.com"
    row = _fake_event_row(
        "evt_004", now, attendees=[{"email": email, "displayName": "Bob"}]
    )
    db = _db_stub([row])
    cfg = _make_cfg()
    entities = await cal_extract(user, db, cfg)

    event = next(e for e in entities if e.entity_type == "Event")
    expected_person_id = person_id_from_email(email)
    rel_targets = [r.target_entity_id for r in event.relationships]
    assert expected_person_id in rel_targets


# ── TC-008 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cal_extract_stable_entity_id_format():
    user = _make_user()
    now = datetime.now(timezone.utc)
    row = _fake_event_row("my_event_id", now)
    db = _db_stub([row])
    cfg = _make_cfg()
    entities = await cal_extract(user, db, cfg)

    event = next(e for e in entities if e.entity_type == "Event")
    assert event.stable_entity_id == "event:my_event_id"


# ── TC-009 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cal_extract_empty_when_no_rows():
    user = _make_user()
    db = _db_stub([])
    cfg = _make_cfg()
    entities = await cal_extract(user, db, cfg)
    assert entities == []


# ── TC-010 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cal_extract_malformed_attendee_email_skipped():
    """Attendee dict with empty email string must be skipped, event kept."""
    user = _make_user()
    now = datetime.now(timezone.utc)
    row = _fake_event_row(
        "evt_005",
        now,
        attendees=[
            {"email": "", "displayName": "Ghost"},
            {"email": "real@example.com"},
        ],
    )
    db = _db_stub([row])
    cfg = _make_cfg()
    entities = await cal_extract(user, db, cfg)
    person_records = [e for e in entities if e.entity_type == "Person"]
    # Only the real email should produce a Person
    assert len(person_records) == 1
    assert person_records[0].source_id == "real@example.com"
