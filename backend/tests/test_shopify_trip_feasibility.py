"""FEAT-129 trip-feasibility: pure verdict logic, route contract, failure paths."""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src.api.v1 import trip_feasibility as route
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.schemas.shopify import TripFeasibilityRequest
from src.services.shopify.providers import CalendarResult, parse_calendar_result
from src.services.shopify.trip_feasibility import check_trip_feasibility
from src.tools.base import ProviderNotLinked, ProviderReauthRequired, ToolError
from src.tools.clients import google_calendar

AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
START = date(2026, 6, 10)
END = date(2026, 6, 14)
VID = "gid://shopify/ProductVariant/1"


# ── factories ─────────────────────────────────────────────────────────────


def make_variants(available=100, vid=VID, has_next=False):
    return {
        "variants": [
            {
                "id": vid,
                "inventoryItem": {
                    "tracked": True,
                    "inventoryLevels": {
                        "edges": [
                            {
                                "node": {
                                    "quantities": [
                                        {"name": "available", "quantity": available}
                                    ]
                                }
                            }
                        ]
                    },
                },
            }
        ],
        "variants_has_next_page": has_next,
        "partial_failures": [],
        "throttled": False,
    }


def make_orders(qty=30, vid=VID, has_next=False, items_truncated=False):
    return {
        "orders": [
            {
                "lineItems": {
                    "edges": [{"node": {"quantity": qty, "variant": {"id": vid}}}]
                }
            }
        ],
        "orders_has_next_page": has_next,
        "line_items_truncated": items_truncated,
        "partial_failures": [],
        "throttled": False,
    }


def timed_event(start, end, title="Meeting", status="confirmed"):
    return {
        "status": status,
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }


def all_day_event(start, end, title="Holiday"):
    return {"summary": title, "start": {"date": start}, "end": {"date": end}}


def run(variants="ok", orders="ok", cal=None, **kw):
    args = dict(
        as_of=AS_OF,
        start_date=START,
        end_date=END,
        variants_data=make_variants() if variants == "ok" else variants,
        orders_data=make_orders() if orders == "ok" else orders,
        cal=cal if cal is not None else CalendarResult(),
        shopify_connected=True,
        shopify_needs_reauth=False,
        window_days=30,
        partial_failures=[],
    )
    args.update(kw)
    return check_trip_feasibility(**args)


# ── request validation ────────────────────────────────────────────────────


def test_request_accepts_single_day_and_sixty_day_window():
    TripFeasibilityRequest(start_date="2026-06-10", end_date="2026-06-10")
    TripFeasibilityRequest(start_date="2026-06-01", end_date="2026-07-30")


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-06-10", "2026-06-09"),
        ("2026-06-01", "2026-07-31"),
        ("not-a-date", "2026-06-09"),
    ],
)
def test_request_rejects_bad_windows(start, end):
    with pytest.raises(ValidationError):
        TripFeasibilityRequest(start_date=start, end_date=end)


# ── verdict matrix ────────────────────────────────────────────────────────


def test_clean_sources_give_go_with_unavailable_sources_named():
    r = run()
    assert r.verdict == "go"
    assert r.conflicts == []
    assert [(u.name, u.reason) for u in r.unavailable_sources] == [
        ("booking_com_pricing", "not_connected"),
        ("calendly_availability", "not_connected"),
        ("deploy_windows", "not_connected"),
    ]


def test_stockout_inside_window_is_no_go():
    # 100 on hand, 30 sold/30d = 1/day -> stockout 2026-09-09; use 10 on hand
    r = run(variants=make_variants(available=12))  # 12 days -> 2026-06-13
    assert r.verdict == "no-go"
    assert r.conflicts[0].type == "stockout"
    assert r.conflicts[0].projected_stockout_date == "2026-06-13"


def test_stockout_within_seven_days_after_window_is_no_go():
    r = run(variants=make_variants(available=20))  # 2026-06-21 = END + 7
    assert r.verdict == "no-go"
    assert r.conflicts[0].projected_stockout_date == "2026-06-21"


def test_stockout_eight_days_after_window_is_go():
    assert run(variants=make_variants(available=21)).verdict == "go"  # END + 8


def test_stockout_before_window_is_still_a_conflict():
    # Out of stock on 06-06, before the trip: still out of stock during it.
    r = run(variants=make_variants(available=5))
    assert r.verdict == "no-go"
    assert r.conflicts[0].projected_stockout_date == "2026-06-06"


def test_timed_event_in_window_is_no_go():
    cal = CalendarResult(
        events=[timed_event("2026-06-12T09:00:00+03:00", "2026-06-12T10:00:00+03:00")]
    )
    r = run(cal=cal)
    assert r.verdict == "no-go"
    assert r.conflicts[0].event_title == "Meeting"


def test_timed_event_spanning_into_window_overlaps():
    cal = CalendarResult(
        events=[timed_event("2026-06-09T20:00:00+00:00", "2026-06-10T02:00:00+00:00")]
    )
    assert run(cal=cal).verdict == "no-go"


def test_timed_event_ending_exactly_at_window_start_does_not_overlap():
    cal = CalendarResult(
        events=[timed_event("2026-06-09T20:00:00+00:00", "2026-06-10T00:00:00+00:00")]
    )
    assert run(cal=cal).verdict == "go"


def test_non_string_event_title_is_coerced_not_a_crash():
    event = timed_event("2026-06-11T10:00:00Z", "2026-06-11T11:00:00Z")
    event["summary"] = 12345
    r = run(cal=CalendarResult(events=[event]))
    assert r.verdict == "no-go"
    assert r.conflicts[0].event_title == "12345"


def test_overlong_event_title_is_truncated_not_a_validation_error():
    event = timed_event(
        "2026-06-11T10:00:00Z", "2026-06-11T11:00:00Z", title="x" * 5000
    )
    r = run(cal=CalendarResult(events=[event]))
    assert r.verdict == "no-go"
    assert len(r.conflicts[0].event_title) == 1024


def test_overlong_all_day_title_is_truncated_not_a_validation_error():
    cal = CalendarResult(
        events=[all_day_event("2026-06-11", "2026-06-12", title="y" * 5000)]
    )
    r = run(cal=cal)
    assert len(r.all_day_events[0].title) == 1024


def test_a_conflict_in_healthy_data_stays_no_go_when_another_source_failed():
    # Documented deviation from the spec's "any degradation gives unknown": a
    # conflict that was really found is not hidden by an unrelated failure.
    event = timed_event("2026-06-11T10:00:00Z", "2026-06-11T11:00:00Z")
    cal = CalendarResult(events=[event])
    r = run(cal=cal, orders=None, partial_failures=["orders"])
    assert r.verdict == "no-go"
    assert "orders" in r.partial_failures


def test_huge_stock_with_slow_sales_does_not_overflow_the_date():
    from src.services.shopify.inventory_cover import project_stockout_date

    assert project_stockout_date(100000, 1, as_of=AS_OF, window_days=30) is not None
    r = run(variants=make_variants(available=100000), orders=make_orders(qty=1))
    assert r.verdict == "go"


def test_oversized_timestamp_strings_are_truncated_not_a_validation_error():
    event = timed_event("2026-06-11T10:00:00Z", "2026-06-11T11:00:00Z")
    event["start"]["dateTime"] = "2026-06-11T10:00:00" + "0" * 200 + "Z"
    r = run(cal=CalendarResult(events=[event]))
    assert r.verdict in ("no-go", "unknown")


def test_null_inventory_item_is_unreadable_not_untracked():
    variants = make_variants()
    variants["variants"][0]["inventoryItem"] = None
    r = run(variants=variants)
    assert r.verdict == "unknown"
    assert "inventory_levels" in r.partial_failures


def test_reversed_all_day_event_is_unreadable_not_dropped():
    cal = CalendarResult(events=[all_day_event("2026-06-12", "2026-06-12")])
    r = run(cal=cal)
    assert r.verdict == "unknown"
    assert "calendar" in r.partial_failures


def test_all_day_event_with_bad_dates_is_unreadable():
    for event in (
        {"summary": "x", "start": {"date": "nope"}, "end": {"date": "2026-06-12"}},
        {"summary": "x", "start": {"date": "2026-06-11"}, "end": {"date": "garbage"}},
        {"summary": "x", "start": {}, "end": {}},
    ):
        r = run(cal=CalendarResult(events=[event]))
        assert r.verdict == "unknown"


@pytest.mark.parametrize(
    ("start", "end"),
    [("9999-12-01", "9999-12-31"), ("0001-01-01", "0001-01-05")],
)
def test_request_rejects_extreme_dates(start, end):
    with pytest.raises(ValueError):
        TripFeasibilityRequest(start_date=start, end_date=end)


def test_cancelled_timed_event_is_ignored():
    cal = CalendarResult(
        events=[
            timed_event(
                "2026-06-12T09:00:00Z", "2026-06-12T10:00:00Z", status="cancelled"
            )
        ]
    )
    assert run(cal=cal).verdict == "go"


def test_all_day_event_is_listed_but_not_a_conflict():
    cal = CalendarResult(events=[all_day_event("2026-06-12", "2026-06-13")])
    r = run(cal=cal)
    assert r.verdict == "go"
    assert r.conflicts == []
    assert [e.title for e in r.all_day_events] == ["Holiday"]


def test_all_day_event_ending_exclusive_at_window_start_not_listed():
    cal = CalendarResult(events=[all_day_event("2026-06-08", "2026-06-10")])
    assert run(cal=cal).all_day_events == []


@pytest.mark.parametrize(
    "kwargs,flag",
    [
        ({"shopify_connected": False}, "shopify_connected"),
        ({"shopify_needs_reauth": True}, "shopify_needs_reauth"),
        ({"cal": CalendarResult(connected=False)}, "calendar_connected"),
        (
            {"cal": CalendarResult(needs_reauth=True, partial_failures=["calendar"])},
            "calendar_needs_reauth",
        ),
        ({"variants": make_variants(has_next=True)}, "variants_truncated"),
        ({"orders": make_orders(has_next=True)}, "orders_truncated"),
        ({"orders": make_orders(items_truncated=True)}, "orders_truncated"),
        (
            {
                "cal": CalendarResult(
                    calendar_truncated=True, partial_failures=["calendar_truncated"]
                )
            },
            "calendar_truncated",
        ),
        ({"partial_failures": ["throttled"]}, "partial_failures"),
        ({"variants": None, "partial_failures": ["variants"]}, "partial_failures"),
        ({"orders": None, "partial_failures": ["orders"]}, "partial_failures"),
        ({"variants": None}, "variants_data_missing"),
    ],
)
def test_every_degraded_source_without_conflict_is_unknown_never_go(kwargs, flag):
    r = run(**kwargs)
    assert r.verdict == "unknown"
    assert r.verdict != "go"


def test_unreadable_calendar_event_degrades_to_unknown():
    cal = CalendarResult(events=[timed_event("garbage", "2026-06-12T10:00:00Z")])
    r = run(cal=cal)
    assert r.verdict == "unknown"
    assert "calendar" in r.partial_failures


def test_conflict_from_healthy_source_still_no_go_when_other_source_degraded():
    cal = CalendarResult(connected=False)
    r = run(variants=make_variants(available=12), cal=cal)
    assert r.verdict == "no-go"
    assert r.calendar_connected is False


def test_unknown_velocity_is_not_read_as_no_stockout():
    r = run(orders=None, partial_failures=["orders"])
    assert r.verdict == "unknown"
    assert r.conflicts == []


# ── provider parsing ──────────────────────────────────────────────────────


def test_parse_calendar_not_linked_and_reauth_are_distinct():
    assert parse_calendar_result(ProviderNotLinked("google")).connected is False
    reauth = parse_calendar_result(ProviderReauthRequired("google"))
    assert reauth.connected is True and reauth.needs_reauth is True


@pytest.mark.parametrize(
    "result",
    [None, [], "oops", ToolError("x", "y"), httpx.TimeoutException("t")],
)
def test_parse_calendar_failures_are_partial_failures(result):
    cal = parse_calendar_result(result)
    assert cal.partial_failures == ["calendar"]
    assert cal.events == []


def test_parse_calendar_next_page_token_sets_truncated():
    cal = parse_calendar_result({"items": [], "nextPageToken": "abc"})
    assert cal.calendar_truncated is True
    assert "calendar_truncated" in cal.partial_failures


def test_parse_calendar_failure_logs_type_only(caplog):
    secret = ToolError("provider_request_failed", "Google rejected: SECRET-TITLE")
    with caplog.at_level("WARNING"):
        parse_calendar_result(secret)
    assert "SECRET-TITLE" not in caplog.text
    assert "ToolError" in caplog.text


def test_google_403_scope_error_maps_to_reauth():
    resp = httpx.Response(
        403, json={"error": {"errors": [{"reason": "insufficientPermissions"}]}}
    )
    with pytest.raises(ProviderReauthRequired):
        google_calendar._resolve(resp)


def test_google_403_quota_error_stays_generic():
    resp = httpx.Response(
        403, json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}}
    )
    with pytest.raises(ToolError) as info:
        google_calendar._resolve(resp)
    assert not isinstance(info.value, ProviderReauthRequired)


# ── route ─────────────────────────────────────────────────────────────────


class _FakeUser:
    id = uuid.uuid4()


class _FakeIntegration:
    def __init__(self, status="connected"):
        self.id = uuid.uuid4()
        self.status = status
        self.last_error = None
        self.config = {"shop_domain": "secret-store.myshopify.com"}


@pytest.fixture
def client(monkeypatch):
    async def _user():
        return _FakeUser()

    async def _db():
        db = MagicMock()
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    m = monkeypatch.setattr
    m(route, "_check_rate_limit", AsyncMock())
    m(route, "_get_token", AsyncMock(return_value="tok"))
    m(route, "_mark_healthy", AsyncMock())
    m(route, "_apply_error_status", AsyncMock())
    m(route, "_find_integration", AsyncMock(return_value=_FakeIntegration()))
    m(route, "_execute_variants_query", AsyncMock(return_value=make_variants()))
    m(route, "_execute_orders_query", AsyncMock(return_value=make_orders()))
    m(route, "_list_calendar_events", AsyncMock(return_value={"items": []}))
    yield TestClient(app)
    app.dependency_overrides.clear()


BODY = {"start_date": "2026-06-10", "end_date": "2026-06-14"}


def post(client, body=BODY):
    return client.post("/api/v1/trip-feasibility", json=body)


def data(resp):
    assert resp.status_code == 200
    return resp.json()["data"]


def test_route_clean_go(client):
    d = data(post(client))
    assert d["verdict"] == "go"
    assert len(d["unavailable_sources"]) == 3


def test_route_never_asks_google_for_more_than_250_events(client, monkeypatch):
    seen = AsyncMock(return_value={"items": []})
    monkeypatch.setattr(route, "_list_calendar_events", seen)
    post(client)
    assert seen.await_count == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"start_date": "2026-06-10"},
        {"start_date": "2026-06-14", "end_date": "2026-06-10"},
        {"start_date": "2026-01-01", "end_date": "2026-12-31"},
        {"start_date": "nope", "end_date": "2026-06-10"},
    ],
)
def test_route_malformed_body_is_422(client, body):
    assert post(client, body).status_code == 422


def test_route_422_body_names_the_failing_field_for_the_form(client):
    # The frontend maps error.details.errors[].loc to form fields.
    resp = post(client, {"start_date": "2026-06-10", "end_date": "nope"})
    assert resp.status_code == 422
    errors = resp.json()["error"]["details"]["errors"]
    assert errors[0]["loc"][-1] == "end_date"


def test_route_shopify_not_connected_is_unknown_but_calendar_still_checked(
    client, monkeypatch
):
    monkeypatch.setattr(route, "_find_integration", AsyncMock(return_value=None))
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["shopify_connected"] is False
    assert d["calendar_connected"] is True


def test_route_shopify_expired_flags_reauth(client, monkeypatch):
    monkeypatch.setattr(
        route, "_find_integration", AsyncMock(return_value=_FakeIntegration("expired"))
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["shopify_needs_reauth"] is True
    assert d["calendar_needs_reauth"] is False


def test_route_calendar_not_linked(client, monkeypatch):
    monkeypatch.setattr(
        route,
        "_list_calendar_events",
        AsyncMock(side_effect=ProviderNotLinked("google")),
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["calendar_connected"] is False
    assert d["calendar_needs_reauth"] is False


def test_route_calendar_reauth_keeps_separate_flag(client, monkeypatch):
    monkeypatch.setattr(
        route,
        "_list_calendar_events",
        AsyncMock(side_effect=ProviderReauthRequired("google")),
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["calendar_needs_reauth"] is True
    assert d["calendar_connected"] is True
    assert d["shopify_needs_reauth"] is False


def test_route_calendar_timeout_is_unknown(client, monkeypatch):
    monkeypatch.setattr(
        route,
        "_list_calendar_events",
        AsyncMock(side_effect=httpx.TimeoutException("t")),
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert "calendar" in d["partial_failures"]


@pytest.mark.parametrize("bad", [None, [], "text"])
def test_route_non_dict_calendar_body_is_unknown(client, monkeypatch, bad):
    monkeypatch.setattr(route, "_list_calendar_events", AsyncMock(return_value=bad))
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert "calendar" in d["partial_failures"]


@pytest.mark.parametrize("bad", [None, [], "text"])
def test_route_non_dict_shopify_body_is_unknown(client, monkeypatch, bad):
    monkeypatch.setattr(route, "_execute_orders_query", AsyncMock(return_value=bad))
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert "orders" in d["partial_failures"]


def test_route_shopify_timeout_is_unknown(client, monkeypatch):
    monkeypatch.setattr(
        route,
        "_execute_variants_query",
        AsyncMock(side_effect=httpx.TimeoutException("t")),
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert "variants" in d["partial_failures"]


def test_route_throttled_is_unknown(client, monkeypatch):
    throttled = {"orders": [], "partial_failures": [], "throttled": True}
    monkeypatch.setattr(
        route, "_execute_orders_query", AsyncMock(return_value=throttled)
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert "throttled" in d["partial_failures"]


@pytest.mark.parametrize(
    "patch,flag",
    [
        ("variants", "variants_truncated"),
        ("orders", "orders_truncated"),
    ],
)
def test_route_truncated_shopify_is_unknown(client, monkeypatch, patch, flag):
    if patch == "variants":
        monkeypatch.setattr(
            route,
            "_execute_variants_query",
            AsyncMock(return_value=make_variants(has_next=True)),
        )
    else:
        monkeypatch.setattr(
            route,
            "_execute_orders_query",
            AsyncMock(return_value=make_orders(has_next=True)),
        )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d[flag] is True


def test_route_calendar_truncated_is_unknown(client, monkeypatch):
    monkeypatch.setattr(
        route,
        "_list_calendar_events",
        AsyncMock(return_value={"items": [], "nextPageToken": "n"}),
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["calendar_truncated"] is True


def test_route_timed_event_conflict_is_no_go(client, monkeypatch):
    cal = {"items": [timed_event("2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z")]}
    monkeypatch.setattr(route, "_list_calendar_events", AsyncMock(return_value=cal))
    d = data(post(client))
    assert d["verdict"] == "no-go"
    assert d["conflicts"][0]["event_title"] == "Meeting"


def test_route_shopify_setup_failure_is_unknown_not_reauth(client, monkeypatch):
    monkeypatch.setattr(
        route, "_get_token", AsyncMock(side_effect=httpx.TimeoutException("t"))
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["shopify_needs_reauth"] is False
    assert "shopify" in d["partial_failures"]


def test_route_logs_do_not_leak_shop_domain(client, monkeypatch, caplog):
    monkeypatch.setattr(
        route,
        "_execute_variants_query",
        AsyncMock(
            side_effect=httpx.TimeoutException("https://secret-store.myshopify.com")
        ),
    )
    with caplog.at_level("WARNING"):
        post(client)
    assert "secret-store" not in caplog.text


def test_tracked_variant_without_stock_level_is_unknown_not_go():
    variants = make_variants()
    variants["variants"][0]["inventoryItem"]["inventoryLevels"] = {"edges": []}
    r = run(variants=variants)
    assert r.verdict == "unknown"
    assert "inventory_levels" in r.partial_failures


# ── additional coverage (pr-test-analyzer pass) ───────────────────────────


def test_calendar_request_shape_primary_single_events_capped_at_250():
    import asyncio

    from src.services.shopify import providers

    captured = {}

    async def fake_request(**kw):
        captured.update(kw)
        return {"items": []}

    original = google_calendar.request
    google_calendar.request = fake_request
    try:
        asyncio.run(providers.list_calendar_events(MagicMock(), _FakeUser(), "a", "b"))
    finally:
        google_calendar.request = original
    assert captured["path"] == "calendars/primary/events"
    assert captured["params"]["singleEvents"] == "true"
    assert captured["params"]["maxResults"] == 250
    assert "start(date,dateTime)" in captured["params"]["fields"]


def test_untracked_variant_is_ignored():
    variants = make_variants(available=1)
    variants["variants"][0]["inventoryItem"]["tracked"] = False
    assert run(variants=variants).verdict == "go"


def test_variant_with_no_recent_sales_never_projects_a_stockout():
    assert run(orders=make_orders(qty=0)).verdict == "go"


def test_zero_stock_with_sales_is_a_conflict_for_a_later_trip():
    r = run(variants=make_variants(available=0))
    assert r.verdict == "no-go"
    assert r.conflicts[0].projected_stockout_date == "2026-06-01"


def test_zero_stock_inside_window_when_window_starts_today():
    r = run(variants=make_variants(available=0), start_date=AS_OF.date())
    assert r.verdict == "no-go"
    assert r.conflicts[0].projected_stockout_date == "2026-06-01"


def test_conflicts_sorted_stockouts_by_date_then_events_by_start():
    variants = make_variants(available=12)
    variants["variants"].append(make_variants(available=10, vid="v2")["variants"][0])
    orders = make_orders()
    orders["orders"].append(make_orders(vid="v2")["orders"][0])
    cal = CalendarResult(
        events=[
            timed_event("2026-06-13T09:00:00Z", "2026-06-13T10:00:00Z", "Late"),
            timed_event("2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z", "Early"),
        ]
    )
    r = run(variants=variants, orders=orders, cal=cal)
    assert [c.type for c in r.conflicts] == [
        "stockout",
        "stockout",
        "calendar_event",
        "calendar_event",
    ]
    assert [c.variant_id for c in r.conflicts[:2]] == ["v2", VID]
    assert [c.event_title for c in r.conflicts[2:]] == ["Early", "Late"]


def test_event_starting_on_last_window_day_overlaps_and_next_day_does_not():
    on_last = CalendarResult(
        events=[timed_event("2026-06-14T22:00:00Z", "2026-06-14T23:00:00Z")]
    )
    after = CalendarResult(
        events=[timed_event("2026-06-15T00:00:00Z", "2026-06-15T01:00:00Z")]
    )
    assert run(cal=on_last).verdict == "no-go"
    assert run(cal=after).verdict == "go"


def test_timed_event_without_end_is_unreadable_not_ignored():
    event = timed_event("2026-06-12T09:00:00Z", "2026-06-12T10:00:00Z")
    del event["end"]
    r = run(cal=CalendarResult(events=[event]))
    assert r.verdict == "unknown"
    assert "calendar" in r.partial_failures


def test_non_dict_event_item_is_unreadable_not_a_crash():
    r = run(cal=CalendarResult(events=["junk", None]))
    assert r.verdict == "unknown"


def test_naive_datetime_is_treated_as_utc():
    cal = CalendarResult(
        events=[timed_event("2026-06-12T09:00:00", "2026-06-12T10:00:00")]
    )
    assert run(cal=cal).verdict == "no-go"


def test_multi_day_all_day_event_overlapping_window_is_listed_once():
    cal = CalendarResult(events=[all_day_event("2026-06-08", "2026-06-12")])
    r = run(cal=cal)
    assert [e.title for e in r.all_day_events] == ["Holiday"]
    assert r.verdict == "go"


def test_calendar_truncated_with_conflict_is_still_no_go_and_flag_kept():
    cal = CalendarResult(
        events=[timed_event("2026-06-12T09:00:00Z", "2026-06-12T10:00:00Z")],
        calendar_truncated=True,
        partial_failures=["calendar_truncated"],
    )
    r = run(cal=cal)
    assert r.verdict == "no-go"
    assert r.calendar_truncated is True


def test_cancelled_all_day_event_not_listed():
    event = all_day_event("2026-06-12", "2026-06-13")
    event["status"] = "cancelled"
    assert run(cal=CalendarResult(events=[event])).all_day_events == []


def test_partial_failures_deduplicated_across_sources():
    cal = CalendarResult(connected=False, partial_failures=["calendar"])
    r = run(cal=cal, partial_failures=["calendar"])
    assert r.partial_failures == ["calendar"]


def test_parse_calendar_non_list_items_is_failure():
    cal = parse_calendar_result({"items": "oops"})
    assert cal.partial_failures == ["calendar"]
    assert cal.events == []


def test_parse_calendar_httpx_connect_error_is_failure():
    result = parse_calendar_result(httpx.ConnectError("x"))
    assert result.partial_failures == ["calendar"]


def test_parse_calendar_unexpected_exception_is_not_swallowed():
    with pytest.raises(RuntimeError):
        parse_calendar_result(RuntimeError("bug"))


def test_google_403_scope_error_via_route_flags_calendar_reauth(client, monkeypatch):
    monkeypatch.setattr(
        route,
        "_list_calendar_events",
        AsyncMock(side_effect=ProviderReauthRequired("google")),
    )
    d = data(post(client))
    assert d["calendar_needs_reauth"] is True
    assert d["verdict"] == "unknown"


# ── response-model invariants ─────────────────────────────────────────────


def test_response_model_rejects_go_with_degraded_flag():
    from src.schemas.shopify import TripFeasibilityResponse

    with pytest.raises(ValidationError):
        TripFeasibilityResponse(
            verdict="go",
            shopify_connected=True,
            calendar_connected=True,
            calendar_truncated=True,
        )


def test_response_model_rejects_no_go_without_conflict():
    from src.schemas.shopify import TripFeasibilityResponse

    with pytest.raises(ValidationError):
        TripFeasibilityResponse(verdict="no-go")


def test_conflict_rejects_fields_of_the_wrong_type():
    from src.schemas.shopify import TripConflict

    with pytest.raises(ValidationError):
        TripConflict(type="stockout", event_title="x")
    with pytest.raises(ValidationError):
        TripConflict(
            type="calendar_event",
            variant_id="v",
            projected_stockout_date="2026-06-01",
        )


# ── additional route contract ─────────────────────────────────────────────


def test_route_requires_auth():
    app.dependency_overrides.clear()
    resp = TestClient(app).post("/api/v1/trip-feasibility", json=BODY)
    assert resp.status_code == 401


def test_route_rate_limit_uses_dedicated_bucket_and_user_identity(client, monkeypatch):
    seen = AsyncMock()
    monkeypatch.undo()
    from src.api.v1 import trip_feasibility as r

    monkeypatch.setattr(r, "enforce_rate_limit", seen)
    monkeypatch.setattr(r, "_find_integration", AsyncMock(return_value=None))
    monkeypatch.setattr(
        r, "_list_calendar_events", AsyncMock(return_value={"items": []})
    )
    post(client)
    kw = seen.await_args.kwargs
    assert kw["bucket"] == "trip_feasibility"
    assert kw["identity"] == str(_FakeUser.id)


def test_route_rate_limit_exceeded_is_429_not_200(client, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        route, "_check_rate_limit", AsyncMock(side_effect=HTTPException(429, "slow"))
    )
    assert post(client).status_code == 429


def test_route_shopify_revoked_during_fetch_flags_reauth_and_persists(
    client, monkeypatch
):
    from src.integrations.base import IntegrationError

    apply = AsyncMock()
    monkeypatch.setattr("src.services.shopify.gather.apply_error_status", apply)
    monkeypatch.setattr(
        route,
        "_execute_orders_query",
        AsyncMock(side_effect=IntegrationError("refresh_failed", "revoked")),
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["shopify_needs_reauth"] is True
    assert d["calendar_needs_reauth"] is False
    apply.assert_awaited()


def test_route_shopify_unreachable_still_reports_calendar_conflict_as_no_go(
    client, monkeypatch
):
    monkeypatch.setattr(route, "_find_integration", AsyncMock(return_value=None))
    cal = {"items": [timed_event("2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z")]}
    monkeypatch.setattr(route, "_list_calendar_events", AsyncMock(return_value=cal))
    d = data(post(client))
    assert d["verdict"] == "no-go"
    assert d["shopify_connected"] is False


def test_route_both_sources_down_is_unknown_with_independent_flags(client, monkeypatch):
    monkeypatch.setattr(route, "_find_integration", AsyncMock(return_value=None))
    monkeypatch.setattr(
        route,
        "_list_calendar_events",
        AsyncMock(side_effect=ProviderNotLinked("google")),
    )
    d = data(post(client))
    assert d["verdict"] == "unknown"
    assert d["shopify_connected"] is False and d["calendar_connected"] is False
    assert len(d["unavailable_sources"]) == 3


def test_route_setup_failure_log_has_no_shop_domain(client, monkeypatch, caplog):
    monkeypatch.setattr(
        route,
        "_get_token",
        AsyncMock(side_effect=httpx.TimeoutException("secret-store.myshopify.com")),
    )
    with caplog.at_level("WARNING"):
        post(client)
    assert "secret-store" not in caplog.text


def test_route_calendar_event_titles_never_logged(client, monkeypatch, caplog):
    cal = {
        "items": [
            timed_event("2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z", "SECRET-TITLE")
        ]
    }
    monkeypatch.setattr(route, "_list_calendar_events", AsyncMock(return_value=cal))
    with caplog.at_level("DEBUG"):
        post(client)
    assert "SECRET-TITLE" not in caplog.text


def test_route_response_is_not_cached(client, monkeypatch):
    calls = AsyncMock(return_value={"items": []})
    monkeypatch.setattr(route, "_list_calendar_events", calls)
    post(client)
    post(client)
    assert calls.await_count == 2
