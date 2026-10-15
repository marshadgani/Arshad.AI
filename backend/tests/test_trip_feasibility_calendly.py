"""FEAT-180 — Calendly as a required live source in the trip check."""

from __future__ import annotations

import typing
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError
from src.schemas.shopify import (
    TripConflict,
    TripFeasibilityResponse,
    UnavailableSourceName,
)
from src.services.shopify import providers as providers_mod
from src.services.shopify.providers import CalendarResult
from src.services.shopify.trip_feasibility import (
    _calendly_findings,
    check_trip_feasibility,
)

START, END = date(2026, 6, 10), date(2026, 6, 14)
AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def meeting(
    name="Intro call",
    start="2026-06-12T09:00:00.000000Z",
    end="2026-06-12T09:30:00.000000Z",
    status="active",
    **extra,
):
    return {
        "name": name,
        "start_time": start,
        "end_time": end,
        "status": status,
        **extra,
    }


def run(**kw):
    args = dict(
        as_of=AS_OF,
        start_date=START,
        end_date=END,
        variants_data={"variants": []},
        orders_data={"orders": []},
        cal=CalendarResult(),
        shopify_connected=True,
        shopify_needs_reauth=False,
        window_days=30,
        partial_failures=[],
        render_config=None,
        supabase_config=None,
        calendly_connected=True,
    )
    args.update(kw)
    return check_trip_feasibility(**args)


def test_connected_clean_calendly_is_go():
    r = run(calendly_events=[])
    assert r.verdict == "go"
    assert r.calendly_connected
    assert "calendly_availability" not in [u.name for u in r.unavailable_sources]


def test_overlapping_meeting_is_no_go_using_name_field():
    r = run(calendly_events=[meeting(name="Board sync")])
    assert r.verdict == "no-go"
    c = r.conflicts[0]
    assert c.type == "calendly_event"
    assert c.calendly_event_title == "Board sync"
    assert c.event_title is None


def test_meeting_outside_window_cancelled_and_other_status_ignored():
    events = [
        meeting(start="2026-06-20T09:00:00Z", end="2026-06-20T10:00:00Z"),
        meeting(status="canceled"),
    ]
    assert run(calendly_events=events).verdict == "go"


def test_meeting_instant_with_offset_is_compared_as_aware_instant():
    # 2026-06-15T01:00+03:00 is 2026-06-14T22:00Z -> inside the window's last day.
    e = meeting(start="2026-06-15T01:00:00+03:00", end="2026-06-15T02:00:00+03:00")
    assert run(calendly_events=[e]).verdict == "no-go"


def test_invitee_data_never_reaches_response():
    e = meeting(event_memberships=[{"user_email": "a@b.c"}], location={"x": "secret"})
    dumped = run(calendly_events=[e]).model_dump_json()
    assert "a@b.c" not in dumped and "secret" not in dumped


def test_title_truncated_and_missing_title_defaulted():
    conflicts, _ = _calendly_findings(
        [meeting(name="x" * 5000), meeting(name=None)], START, END
    )
    assert len(conflicts[0].calendly_event_title) == 1024
    assert "(no title)" in [c.calendly_event_title for c in conflicts]


def test_unreadable_event_degrades_to_unknown():
    r = run(calendly_events=[meeting(start="garbage")])
    assert r.verdict == "unknown"
    assert "calendly" in r.partial_failures


@pytest.mark.parametrize(
    "kw",
    [
        {"calendly_connected": False},
        {"calendly_needs_reauth": True},
        {"calendly_truncated": True},
        {"calendly_partial_failure": True},
    ],
)
def test_degraded_calendly_is_unknown_never_go(kw):
    r = run(calendly_events=[], **kw)
    assert r.verdict == "unknown"


def test_not_connected_carries_state_via_flag_not_unavailable_sources():
    r = run(calendly_connected=False)
    assert not r.calendly_connected
    assert "calendly_availability" not in [u.name for u in r.unavailable_sources]


def test_conflict_stays_no_go_when_calendly_degraded_elsewhere():
    r = run(calendly_events=[meeting()], calendly_truncated=True)
    assert r.verdict == "no-go"
    assert r.calendly_truncated


def test_conflict_validator_isolates_calendly_and_calendar_fields():
    TripConflict(
        type="calendly_event",
        calendly_event_title="a",
        calendly_event_start="s",
        calendly_event_end="e",
    )
    with pytest.raises(ValidationError):
        TripConflict(
            type="calendly_event", event_title="a", event_start="s", event_end="e"
        )
    with pytest.raises(ValidationError):
        TripConflict(
            type="calendar_event",
            event_title="a",
            event_start="s",
            event_end="e",
            calendly_event_title="a",
        )


# ── route seam ────────────────────────────────────────────────────────────


class _Row:
    def __init__(self, status="connected", config=None):
        self.id = uuid.uuid4()
        self.status = status
        self.config = (
            config
            if config is not None
            else {"user_uri": "https://api.calendly.com/users/U"}
        )
        self.last_error = None


def _db(creds):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=creds)
    db.commit = AsyncMock()
    return db


def _creds(extra=None):
    c = MagicMock()
    c.encrypted_key = "blob"
    c.extra = extra or {}
    return c


@pytest.fixture
def seams(monkeypatch):
    monkeypatch.setattr(providers_mod, "decrypt", lambda _: "tok")
    return monkeypatch


async def _resolve(db):
    return await providers_mod.resolve_calendly("u", db, START, END)


@pytest.mark.asyncio
async def test_no_row_is_not_connected(seams):
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=None)
    )
    r = await _resolve(_db(None))
    assert not r.connected


@pytest.mark.asyncio
async def test_expired_row_needs_reauth_without_calling_api(seams):
    seams.setattr(
        providers_mod,
        "_find_calendly_integration",
        AsyncMock(return_value=_Row("expired")),
    )
    fetch = AsyncMock()
    seams.setattr(providers_mod, "_fetch_calendly_events", fetch)
    r = await _resolve(_db(_creds()))
    assert r.connected and r.needs_reauth
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_401_sets_reauth_and_marks_expired(seams):
    row = _Row()
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=row)
    )
    resp = httpx.Response(401, request=httpx.Request("GET", "https://x"))
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(
            side_effect=httpx.HTTPStatusError("x", request=resp.request, response=resp)
        ),
    )
    r = await _resolve(_db(_creds()))
    assert r.needs_reauth and row.status == "expired"


@pytest.mark.asyncio
async def test_500_and_network_errors_are_partial_failures(seams):
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=_Row())
    )
    resp = httpx.Response(500, request=httpx.Request("GET", "https://x"))
    for exc in (
        httpx.HTTPStatusError("x", request=resp.request, response=resp),
        httpx.ConnectError("down"),
    ):
        seams.setattr(
            providers_mod, "_fetch_calendly_events", AsyncMock(side_effect=exc)
        )
        r = await _resolve(_db(_creds()))
        assert r.connected and r.partial_failure and not r.needs_reauth


@pytest.mark.asyncio
async def test_user_uri_falls_back_to_credential_extra_then_fails_closed(seams):
    fetch = AsyncMock(return_value={"collection": []})
    seams.setattr(providers_mod, "_fetch_calendly_events", fetch)
    seams.setattr(
        providers_mod,
        "_find_calendly_integration",
        AsyncMock(return_value=_Row(config={})),
    )
    r = await _resolve(_db(_creds({"user_uri": "https://api.calendly.com/users/X"})))
    assert r.connected and not r.partial_failure
    assert fetch.await_args.args[0].endswith("/users/X")
    r = await _resolve(_db(_creds({})))
    assert r.partial_failure


@pytest.mark.asyncio
async def test_cap_or_next_page_marks_truncated(seams):
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=_Row())
    )
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(return_value={"collection": [{}] * 100}),
    )
    assert (await _resolve(_db(_creds()))).truncated
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(
            return_value={"collection": [], "pagination": {"next_page_token": "t"}}
        ),
    )
    assert (await _resolve(_db(_creds()))).truncated
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(return_value={"collection": [{}] * 3}),
    )
    assert not (await _resolve(_db(_creds()))).truncated


@pytest.mark.asyncio
async def test_malformed_collection_is_partial_failure(seams):
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=_Row())
    )
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(return_value={"collection": "no"}),
    )
    assert (await _resolve(_db(_creds()))).partial_failure


# ── window edges and ignored data ─────────────────────────────────────────


def test_window_boundaries_are_half_open_on_whole_utc_days():
    # Window is [2026-06-10T00:00Z, 2026-06-15T00:00Z).
    before = meeting(start="2026-06-09T23:00:00Z", end="2026-06-10T00:00:00Z")
    after = meeting(start="2026-06-15T00:00:00Z", end="2026-06-15T01:00:00Z")
    assert run(calendly_events=[before, after]).verdict == "go"
    last_minute = meeting(start="2026-06-14T23:30:00Z", end="2026-06-15T00:30:00Z")
    assert run(calendly_events=[last_minute]).verdict == "no-go"


def test_meeting_with_missing_status_is_unreadable_not_ignored():
    e = meeting()
    del e["status"]
    conflicts, unreadable = _calendly_findings([e], START, END)
    assert conflicts == [] and unreadable
    assert run(calendly_events=[e]).verdict == "unknown"


def test_non_dict_event_is_unreadable():
    assert _calendly_findings(["x"], START, END) == ([], True)


def test_reauth_ignores_stale_events_and_is_unknown():
    r = run(calendly_events=[meeting()], calendly_needs_reauth=True)
    assert r.verdict == "unknown"
    assert r.conflicts == []
    assert r.calendly_needs_reauth


def test_not_connected_ignores_events():
    r = run(calendly_events=[meeting()], calendly_connected=False)
    assert r.verdict == "unknown" and r.conflicts == []


def test_partial_failure_and_truncation_labels_reach_partial_failures():
    r = run(calendly_partial_failure=True, calendly_truncated=True)
    assert "calendly" in r.partial_failures
    assert "calendly_truncated" in r.partial_failures
    assert r.calendly_truncated


def test_go_response_invariant_rejects_degraded_calendly():
    base = dict(verdict="go", shopify_connected=True, calendar_connected=True)
    TripFeasibilityResponse(**base, calendly_connected=True)
    for bad in (
        {"calendly_connected": False},
        {"calendly_connected": True, "calendly_needs_reauth": True},
        {"calendly_connected": True, "calendly_truncated": True},
    ):
        with pytest.raises(ValidationError):
            TripFeasibilityResponse(**base, **bad)


def test_unavailable_source_name_no_longer_lists_calendly_stub():
    names = typing.get_args(UnavailableSourceName)
    assert "calendly_availability" not in names
    assert "booking_com_pricing" in names


# ── provider seams not covered above ──────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_credentials_row_is_partial_failure(seams):
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=_Row())
    )
    fetch = AsyncMock()
    seams.setattr(providers_mod, "_fetch_calendly_events", fetch)
    r = await _resolve(_db(None))
    assert r.connected and r.partial_failure
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_403_also_means_reauth(seams):
    row = _Row()
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=row)
    )
    resp = httpx.Response(403, request=httpx.Request("GET", "https://x"))
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(
            side_effect=httpx.HTTPStatusError("x", request=resp.request, response=resp)
        ),
    )
    r = await _resolve(_db(_creds()))
    assert r.needs_reauth and row.status == "expired"
    assert "tok" not in (row.last_error or "")


@pytest.mark.asyncio
async def test_429_is_partial_failure_not_reauth(seams):
    row = _Row()
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=row)
    )
    resp = httpx.Response(429, request=httpx.Request("GET", "https://x"))
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(
            side_effect=httpx.HTTPStatusError("x", request=resp.request, response=resp)
        ),
    )
    r = await _resolve(_db(_creds()))
    assert r.partial_failure and not r.needs_reauth and row.status == "connected"


@pytest.mark.asyncio
async def test_non_json_body_is_partial_failure(seams):
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=_Row())
    )
    seams.setattr(
        providers_mod,
        "_fetch_calendly_events",
        AsyncMock(side_effect=ValueError("not json")),
    )
    assert (await _resolve(_db(_creds()))).partial_failure


@pytest.mark.asyncio
async def test_decrypt_failure_propagates_instead_of_reading_as_unknown(seams):
    def boom(_):
        raise ValueError("bad key")

    seams.setattr(providers_mod, "decrypt", boom)
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=_Row())
    )
    with pytest.raises(ValueError):
        await _resolve(_db(_creds()))


@pytest.mark.asyncio
async def test_fetch_passes_user_uri_and_window_with_margin(seams):
    seams.setattr(
        providers_mod, "_find_calendly_integration", AsyncMock(return_value=_Row())
    )
    fetch = AsyncMock(return_value={"collection": []})
    seams.setattr(providers_mod, "_fetch_calendly_events", fetch)
    await _resolve(_db(_creds()))
    uri, key, tmin, tmax = fetch.await_args.args
    assert uri == "https://api.calendly.com/users/U" and key == "tok"
    assert tmin.startswith("2026-06-09") and tmax.startswith("2026-06-16")


# ── route: always-200 and flags ───────────────────────────────────────────


@pytest.fixture
def route_client(monkeypatch):
    from fastapi.testclient import TestClient
    from src.api.v1 import trip_feasibility as route
    from src.auth.dependencies import get_current_user
    from src.main import app
    from src.models.database import get_db

    user = MagicMock(id=uuid.uuid4())

    async def _user():
        return user

    async def _get_db():
        yield MagicMock(commit=AsyncMock())

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _get_db
    m = monkeypatch.setattr
    m(route, "_check_rate_limit", AsyncMock())
    m(route, "_find_integration", AsyncMock(return_value=None))
    m(route, "_find_infra_integrations", AsyncMock(return_value=(None, None)))
    m(route, "_list_calendar_events", AsyncMock(return_value={"items": []}))
    client = TestClient(app)
    client.set_calendly = lambda result: m(
        route.providers, "resolve_calendly", AsyncMock(return_value=result)
    )
    client.user_id = str(user.id)
    client.resolve_spy = lambda spy: m(route.providers, "resolve_calendly", spy)
    yield client
    app.dependency_overrides.clear()


BODY = {"start_date": "2026-06-10", "end_date": "2026-06-14"}
FetchResult = providers_mod.CalendlyFetchResult


@pytest.mark.parametrize(
    "result,flag,failure",
    [
        (FetchResult(), "calendly_connected", None),
        (FetchResult(connected=True, needs_reauth=True), "calendly_needs_reauth", None),
        (FetchResult(connected=True, truncated=True), "calendly_truncated", "calendly_truncated"),
        (FetchResult(connected=True, partial_failure=True), None, "calendly"),
    ],
)
def test_route_degraded_calendly_is_200_unknown(route_client, result, flag, failure):
    route_client.set_calendly(result)
    resp = route_client.post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["verdict"] == "unknown"
    if flag == "calendly_connected":
        assert data[flag] is False
    elif flag:
        assert data[flag] is True
    if failure:
        assert failure in data["partial_failures"]
    assert "calendly_availability" not in [
        u["name"] for u in data["unavailable_sources"]
    ]


def test_route_calendly_meeting_is_no_go_without_invitee_data(route_client):
    route_client.set_calendly(
        FetchResult(
            connected=True,
            events=[meeting(event_memberships=[{"user_email": "a@b.c"}])],
        )
    )
    resp = route_client.post("/api/v1/trip-feasibility", json=BODY)
    data = resp.json()["data"]
    assert data["verdict"] == "no-go"
    assert data["conflicts"][0]["type"] == "calendly_event"
    assert "a@b.c" not in resp.text


def test_route_reads_calendly_once_for_the_current_user(route_client):
    seen = []

    async def spy(user_id, db, start, end):
        seen.append((user_id, start, end))
        return FetchResult()

    route_client.resolve_spy(spy)
    route_client.post("/api/v1/trip-feasibility", json=BODY)
    assert seen == [(route_client.user_id, START, END)]
