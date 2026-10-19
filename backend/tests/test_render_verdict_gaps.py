"""FEAT-132 gap-closing tests (pr-test-analyzer pass).

Adds what the first suite left open: boundary behaviour of the classifier,
level handling at the parse step and through the real client into the route,
route degradation branches (not-live, in-progress, 401, bad key, exploding
seams), log-safety, request shape and scoping. No network, DB or GitHub.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from src.api.v1 import render_deploys as route
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.services.render import client as rc
from src.services.render import verdict as v
from src.services.render.models import (
    DeployRecord,
    LogRecord,
    MetricWindow,
    normalise_level,
)

T0 = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
FINISH = T0 + timedelta(minutes=3)
LATER = FINISH + timedelta(hours=3)
SID = "srv-abc123"
URL = f"/api/v1/render/services/{SID}/deploys/dep-1/verdict"
CREATED = datetime.now(timezone.utc) - timedelta(hours=10)


def _rec(level, ts=T0, message="m"):
    return LogRecord(timestamp=ts, level=level, message=message)


def _mix(**counts):
    return [_rec(lvl) for lvl, n in counts.items() for _ in range(n)]


def _m(mean=None, failed=False):
    return MetricWindow(mean=mean, fetch_failed=failed)


def _verdict(before, after, *, cpu=(None, None), lat=(None, None), mem=(None, None)):
    bw, aw = v.compute_windows(T0, FINISH, LATER)
    return v.compute_verdict_from_data(
        before,
        after,
        False,
        False,
        bw,
        aw,
        _m(cpu[0]),
        _m(cpu[1]),
        _m(mem[0]),
        _m(mem[1]),
        _m(lat[0]),
        _m(lat[1]),
        True,
        False,
    )


# ── Level: parse step, normalisation, classification ─────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ERROR", "error"),
        (" Fatal ", "critical"),
        ("warn", "warning"),
        ("err", "error"),
        ("trace", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
        (3, "unknown"),
    ],
)
def test_normalise_level_aliases_and_fallback(raw, expected):
    assert normalise_level(raw) == expected


def test_parse_log_without_level_label_is_unknown_not_dropped():
    rec = rc._parse_log({"timestamp": "2026-10-19T06:01:00Z", "message": "x"})
    assert isinstance(rec, LogRecord) and rec.level == "unknown"


def test_parse_log_reads_level_from_label_not_message():
    rec = rc._parse_log(
        {
            "timestamp": "2026-10-19T06:01:00Z",
            "message": "ERROR: this is only text",
            "labels": [{"name": "level", "value": "info"}],
        }
    )
    assert rec.level == "info"
    assert v.classify_logs([rec])["error"] == 0


def test_parse_log_truncates_message_and_treats_naive_timestamp_as_utc():
    rec = rc._parse_log(
        {"timestamp": "2026-10-19T06:01:00", "message": "x" * 1000, "labels": []}
    )
    assert len(rec.message) == 200 and rec.timestamp.tzinfo is not None


def test_classify_logs_counts_every_level_and_unknown():
    counts = v.classify_logs(
        _mix(error=2, critical=1, warning=3, info=4, debug=5, unknown=6)
    )
    assert counts == {
        "error": 2,
        "critical": 1,
        "warning": 3,
        "info": 4,
        "debug": 5,
        "unknown": 6,
    }


def test_critical_counts_as_error_and_warning_does_not():
    r = _verdict(_mix(info=5), _mix(critical=3, warning=10, info=2))
    assert r.before_error_count == 0 and r.after_error_count == 3
    assert r.verdict == "regression"


def test_message_text_never_drives_error_count():
    noisy = [_rec("info", message="ERROR CRITICAL exception") for _ in range(6)]
    r = _verdict(noisy, noisy)
    assert r.before_error_count == r.after_error_count == 0


def test_mixed_unknown_and_known_levels_is_not_level_unavailable():
    r = _verdict(_mix(unknown=3, info=3), _mix(info=6))
    assert not any(f.startswith("log_level_unavailable") for f in r.partial_failures)


def test_after_window_with_only_unlabelled_logs_is_unknown():
    r = _verdict(_mix(info=5), _mix(unknown=5))
    assert r.verdict == "unknown"
    assert "log_level_unavailable_after" in r.partial_failures


# ── Windows and rate ─────────────────────────────────────────────────────


def test_windows_are_adjacent_to_deploy_and_equal_length():
    before, after = v.compute_windows(T0, FINISH, LATER)
    assert before.end == T0 and after.start == FINISH
    assert (before.end - before.start) == (after.end - after.start)
    assert (before.end - before.start).total_seconds() == v._WINDOW_LENGTH_SECONDS


def test_after_window_complete_exactly_at_as_of_boundary():
    _, after = v.compute_windows(T0, FINISH, FINISH + timedelta(hours=1))
    assert after.is_complete is True
    _, after = v.compute_windows(
        T0, FINISH, FINISH + timedelta(hours=1) - timedelta(seconds=1)
    )
    assert after.is_complete is False


def test_missing_finish_is_never_read_as_now():
    assert v.compute_windows(T0, None, T0 + timedelta(days=30)) is None


@pytest.mark.parametrize(
    "count,seconds,expected",
    [(60, 3600, 1.0), (0, 3600, 0.0), (10, 600, 1.0), (5, 0, 0.0), (5, -1, 0.0)],
)
def test_error_rate_is_per_minute_and_zero_safe(count, seconds, expected):
    assert v.compute_error_rate(count, seconds) == pytest.approx(expected)


# ── Classifier boundaries and metric rules ───────────────────────────────


def _classify(
    before_rate, after_rate, *, failures=(), cpu=(None, None), lat=(None, None)
):
    bw, aw = v.compute_windows(T0, FINISH, LATER)
    return v.classify_verdict(
        before_rate, after_rate, bw, aw, failures, cpu[0], cpu[1], lat[0], lat[1]
    )


def test_exactly_multiplier_is_not_regression_just_above_is():
    base = 2.0
    assert _classify(base, base * v._REGRESSION_RATE_MULTIPLIER) == "neutral"
    assert _classify(base, base * v._REGRESSION_RATE_MULTIPLIER + 0.01) == "regression"


def test_errors_appearing_from_a_clean_baseline_is_regression():
    assert _classify(0.0, 0.1) == "regression"
    assert _classify(0.0, 0.0) == "neutral"


def test_large_error_drop_alone_is_improvement():
    assert _classify(10.0, 2.0) == "improvement"


def test_small_drop_needs_both_cpu_and_latency_lower():
    assert _classify(10.0, 8.0, cpu=(0.5, 0.4), lat=(100, 80)) == "improvement"
    assert _classify(10.0, 8.0, cpu=(0.5, 0.4), lat=(100, 120)) == "neutral"
    assert _classify(10.0, 8.0, cpu=(0.5, 0.4), lat=(None, None)) == "neutral"


def test_failed_metric_never_allows_improvement_or_neutral():
    for name in ("cpu", "memory", "latency"):
        assert _classify(10.0, 1.0, failures=[name]) == "unknown"
        assert _classify(3.0, 3.0, failures=[name]) == "unknown"


@pytest.mark.parametrize(
    "flag",
    [
        "insufficient_log_samples_before",
        "insufficient_log_samples_after",
        "logs",
        "log_level_unavailable_before",
        "log_level_unavailable_after",
        "log_truncated_before",
        "log_truncated_after",
    ],
)
def test_each_blocking_failure_beats_regression(flag):
    assert _classify(1.0, 50.0, failures=[flag]) == "unknown"


def test_failed_memory_metric_surfaces_in_partial_failures():
    bw, aw = v.compute_windows(T0, FINISH, LATER)
    ok = _m(1.0)
    r = v.compute_verdict_from_data(
        _mix(info=5),
        _mix(info=5),
        False,
        False,
        bw,
        aw,
        ok,
        ok,
        _m(failed=True),
        ok,
        ok,
        ok,
        True,
        False,
    )
    assert "memory" in r.partial_failures and r.verdict == "unknown"


def test_both_windows_truncated_sets_flag_and_unknown():
    bw, aw = v.compute_windows(T0, FINISH, LATER)
    m = _m(1.0)
    r = v.compute_verdict_from_data(
        _mix(info=5), _mix(info=5), True, True, bw, aw, m, m, m, m, m, m, True, False
    )
    assert r.log_truncated is True and r.verdict == "unknown"
    assert {"log_truncated_before", "log_truncated_after"} <= set(r.partial_failures)


def test_response_reports_rates_and_metric_means():
    r = _verdict(
        _mix(error=2, info=4),
        _mix(error=2, info=4),
        cpu=(0.4, 0.5),
        lat=(100.0, 90.0),
        mem=(10.0, 11.0),
    )
    assert r.before_error_rate == pytest.approx(2 / 60)
    assert (r.cpu_before_mean, r.cpu_after_mean) == (0.4, 0.5)
    assert (r.latency_before_mean, r.memory_after_mean) == (100.0, 11.0)


# ── Client ───────────────────────────────────────────────────────────────


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)

    def _raise():
        if status >= 400:
            raise httpx.HTTPStatusError(
                "SECRET-URL-TEXT", request=MagicMock(), response=r
            )

    r.raise_for_status = _raise
    return r


def _http(*responses):
    c = MagicMock()
    c.get = AsyncMock(side_effect=list(responses))
    return c


def _entry(level, ts="2026-10-19T06:01:00Z"):
    return {
        "timestamp": ts,
        "message": "m",
        "labels": [{"name": "level", "value": level}],
    }


@pytest.mark.asyncio
async def test_fetch_logs_missing_cursor_stops_and_reports_truncated_once():
    page = _resp(200, {"logs": [_entry("error")] * 3, "hasMore": True})
    c = _http(page, page)
    recs, truncated, code = await rc.fetch_logs("srv-a", "tea-1", T0, FINISH, "k", c)
    assert len(recs) == 3, "a page must never be re-requested and double counted"
    assert truncated is True and code is None
    assert c.get.await_count == 1


@pytest.mark.asyncio
async def test_fetch_logs_malformed_entry_degrades_without_raising():
    c = _http(_resp(200, {"logs": [{"message": "no timestamp"}], "hasMore": False}))
    recs, truncated, code = await rc.fetch_logs("srv-a", "tea-1", T0, FINISH, "k", c)
    assert recs == [] and code == "fetch_error"


@pytest.mark.asyncio
async def test_fetch_logs_timeout_is_fetch_error(monkeypatch):
    async def _boom(*a, **kw):
        raise TimeoutError

    monkeypatch.setattr(rc, "_get", _boom)
    _, _, code = await rc.fetch_logs("srv-a", "tea-1", T0, FINISH, "k", MagicMock())
    assert code == "fetch_error"


@pytest.mark.asyncio
async def test_fetch_logs_request_shape_scopes_to_owner_and_service():
    c = _http(_resp(200, {"logs": [], "hasMore": False}))
    await rc.fetch_logs("srv-a", "tea-1", T0, FINISH, "rnd_key", c)
    call = c.get.await_args
    assert call.kwargs["headers"] == {"Authorization": "Bearer rnd_key"}
    params = call.kwargs["params"]
    assert params["ownerId"] == "tea-1" and params["resource"] == "srv-a"
    assert params["startTime"].endswith("Z") and params["limit"] <= 100
    assert "rnd_key" not in str(params) and "rnd_key" not in call.args[0]


@pytest.mark.asyncio
async def test_fetch_logs_failure_logs_only_type_and_status(caplog):
    with caplog.at_level(logging.DEBUG):
        await rc.fetch_logs(
            "srv-a", "tea-1", T0, FINISH, "rnd_key", _http(_resp(503, {}))
        )
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "HTTPStatusError" in text and "503" in text
    assert "SECRET-URL-TEXT" not in text and "rnd_key" not in text
    assert "api.render.com" not in text


@pytest.mark.asyncio
async def test_fetch_metric_empty_series_is_missing_data_not_a_quiet_metric():
    res = await rc.fetch_metric(
        "srv-a", T0, FINISH, "memory", "k", _http(_resp(200, []))
    )
    assert res.mean is None and res.sample_count == 0
    assert res.fetch_failed is True and res.failure_code == "no_data"


@pytest.mark.asyncio
async def test_fetch_metric_401_is_needs_reauth_and_unknown_metric_fails():
    bad = await rc.fetch_metric("srv-a", T0, FINISH, "cpu", "k", _http(_resp(401, {})))
    assert bad.fetch_failed and bad.failure_code == "needs_reauth"
    nope = await rc.fetch_metric("srv-a", T0, FINISH, "disk", "k", _http())
    assert nope.fetch_failed


@pytest.mark.asyncio
async def test_fetch_metric_ignores_non_numeric_points_and_uses_p95_latency():
    body = [
        {"values": [{"value": 2.0}, {"value": "x"}, {"value": None}, {"value": 4.0}]}
    ]
    c = _http(_resp(200, body))
    res = await rc.fetch_metric("srv-a", T0, FINISH, "latency", "k", c)
    assert res.mean == 3.0 and res.sample_count == 2
    assert c.get.await_args.kwargs["params"]["quantile"] == "0.95"
    assert c.get.await_args.args[0].endswith("/metrics/http-latency")


@pytest.mark.asyncio
async def test_fetch_deploy_record_parses_wrapped_payload_and_in_progress():
    body = {
        "deploy": {
            "id": "dep-1",
            "status": "build_in_progress",
            "createdAt": "2026-10-19T06:00:00Z",
            "finishedAt": None,
        }
    }
    rec = await rc.fetch_deploy_record("srv-a", "dep-1", "k", _http(_resp(200, body)))
    assert rec.finished_at is None and rec.created_at.tzinfo is not None
    assert rec.status == "build_in_progress"


@pytest.mark.asyncio
async def test_fetch_deploy_record_malformed_and_401_raise():
    with pytest.raises(ValueError):
        await rc.fetch_deploy_record("srv-a", "d", "k", _http(_resp(200, {"x": 1})))
    with pytest.raises(httpx.HTTPStatusError):
        await rc.fetch_deploy_record("srv-a", "d", "k", _http(_resp(401, {})))


# ── Route ────────────────────────────────────────────────────────────────


class _User:
    id = uuid.uuid4()


def _row(owner="tea-1"):
    row = MagicMock()
    row.status = "connected"
    row.config = {
        "services": [
            {"id": SID, "name": "api", "owner_id": owner, "latest_deploy_id": "dep-1"}
        ]
    }
    return row


def _deploy(status="live", finished=True):
    return DeployRecord(
        service_id=SID,
        deploy_id="dep-1",
        created_at=CREATED,
        finished_at=CREATED + timedelta(minutes=3) if finished else None,
        status=status,
    )


@pytest.fixture
def ctx(monkeypatch):
    db = MagicMock()
    db.rollback = AsyncMock()

    async def _db():
        yield db

    async def _user():
        return _User()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    mocks = {
        "rate": AsyncMock(),
        "find": AsyncMock(return_value=_row()),
        "key": AsyncMock(return_value="rnd_key"),
        "deploy": AsyncMock(return_value=_deploy()),
        "logs": AsyncMock(return_value=(_mix(error=1, info=5), False, None)),
        "metric": AsyncMock(return_value=MetricWindow(mean=1.0, sample_count=3)),
        "db": db,
    }
    monkeypatch.setattr(route, "_check_rate_limit", mocks["rate"])
    monkeypatch.setattr(route, "_find_render_integration", mocks["find"])
    monkeypatch.setattr(route, "_get_api_key", mocks["key"])
    monkeypatch.setattr(route, "_fetch_deploy_record", mocks["deploy"])
    monkeypatch.setattr(route, "_fetch_logs", mocks["logs"])
    monkeypatch.setattr(route, "_fetch_metric", mocks["metric"])
    mocks["client"] = TestClient(app)
    yield mocks
    app.dependency_overrides.clear()


def _get(ctx, url=URL):
    resp = ctx["client"].get(url)
    assert resp.status_code == 200
    return resp.json()["data"]


@pytest.mark.parametrize(
    "status", ["build_failed", "update_failed", "pre_deploy_failed", "canceled"]
)
def test_deploy_that_never_went_live_is_unknown(ctx, status):
    ctx["deploy"].return_value = _deploy(status=status)
    d = _get(ctx)
    assert d["verdict"] == "unknown" and d["partial_failures"] == ["deploy_not_live"]
    ctx["logs"].assert_not_awaited()


def test_deploy_still_running_is_unknown_and_fetches_nothing(ctx):
    ctx["deploy"].return_value = _deploy(status="build_in_progress", finished=False)
    d = _get(ctx)
    assert d["partial_failures"] == ["deploy_in_progress"] and d["verdict"] == "unknown"
    ctx["logs"].assert_not_awaited()
    ctx["metric"].assert_not_awaited()


def test_recent_deploy_after_window_not_elapsed_is_unknown(ctx):
    recent = datetime.now(timezone.utc) - timedelta(minutes=10)
    ctx["deploy"].return_value = DeployRecord(
        service_id=SID,
        deploy_id="dep-1",
        created_at=recent - timedelta(minutes=3),
        finished_at=recent,
        status="live",
    )
    d = _get(ctx)
    assert d["verdict"] == "unknown" and "window_incomplete" in d["partial_failures"]


def test_deploy_lookup_401_sets_needs_reauth(ctx):
    resp = MagicMock(status_code=401)
    ctx["deploy"].side_effect = httpx.HTTPStatusError(
        "x", request=MagicMock(), response=resp
    )
    d = _get(ctx)
    assert d["needs_reauth"] is True and d["verdict"] == "unknown"
    assert d["partial_failures"] == ["deploy_record"]


def test_deploy_lookup_5xx_is_not_reauth(ctx):
    resp = MagicMock(status_code=503)
    ctx["deploy"].side_effect = httpx.HTTPStatusError(
        "x", request=MagicMock(), response=resp
    )
    assert _get(ctx)["needs_reauth"] is False


def test_unreadable_or_missing_api_key_needs_reauth_without_render_calls(ctx):
    ctx["key"].return_value = None
    d = _get(ctx)
    assert d["needs_reauth"] is True and d["connected"] is True
    assert d["verdict"] == "unknown"
    ctx["deploy"].assert_not_awaited()


def test_malformed_snapshot_services_is_service_not_found_not_500(ctx):
    row = _row()
    row.config = {"services": "oops"}
    ctx["find"].return_value = row
    assert _get(ctx)["partial_failures"] == ["service_not_found"]


def test_exploding_log_seam_degrades_never_500(ctx):
    ctx["logs"].side_effect = RuntimeError("secret-boom")
    d = _get(ctx)
    assert d["verdict"] == "unknown" and "logs" in d["partial_failures"]


def test_exploding_metric_seam_degrades_never_500(ctx):
    ctx["metric"].side_effect = RuntimeError("secret-boom")
    d = _get(ctx)
    assert d["verdict"] == "unknown"
    assert {"cpu", "memory", "latency"} <= set(d["partial_failures"])


def test_failures_log_only_exception_type(ctx, caplog):
    ctx["logs"].side_effect = RuntimeError("secret-boom")
    resp = MagicMock(status_code=503)
    with caplog.at_level(logging.DEBUG):
        _get(ctx)
        ctx["deploy"].side_effect = httpx.HTTPStatusError(
            "secret-boom", request=MagicMock(), response=resp
        )
        _get(ctx)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "secret-boom" not in text and "rnd_key" not in text


def test_rate_limit_runs_before_any_lookup_and_429_makes_no_render_call(ctx):
    from fastapi import HTTPException

    ctx["rate"].side_effect = HTTPException(429, "slow")
    assert ctx["client"].get(URL).status_code == 429
    ctx["find"].assert_not_awaited()
    ctx["deploy"].assert_not_awaited()


def test_invalid_service_id_is_rejected_before_rate_limit_and_lookup(ctx):
    resp = ctx["client"].get("/api/v1/render/services/SRV-ABC/deploys/d/verdict")
    assert resp.status_code == 422
    ctx["find"].assert_not_awaited()


def test_integration_lookup_is_scoped_to_calling_user(ctx):
    _get(ctx)
    assert ctx["find"].await_args.args[0] == str(_User.id)
    assert ctx["rate"].await_args.args[0] == str(_User.id)


def test_db_connection_released_before_render_calls(ctx):
    order = []
    ctx["db"].rollback.side_effect = lambda: order.append("rollback")

    async def _deploy_spy(*a, **kw):
        order.append("render")
        return _deploy()

    ctx["deploy"].side_effect = _deploy_spy
    _get(ctx)
    assert order[:2] == ["rollback", "render"]


def test_one_log_window_each_side_and_three_metrics_per_side(ctx):
    _get(ctx)
    assert ctx["logs"].await_count == 2
    assert ctx["metric"].await_count == 6
    (b_start, b_end), (a_start, a_end) = (
        ctx["logs"].await_args_list[0].args[2:4],
        ctx["logs"].await_args_list[1].args[2:4],
    )
    assert b_end == CREATED and a_start == CREATED + timedelta(minutes=3)
    assert b_end - b_start == a_end - a_start


def test_response_envelope_has_all_contract_keys(ctx):
    d = _get(ctx)
    assert set(d) == {
        "verdict",
        "before_error_count",
        "after_error_count",
        "before_error_rate",
        "after_error_rate",
        "cpu_before_mean",
        "cpu_after_mean",
        "memory_before_mean",
        "memory_after_mean",
        "latency_before_mean",
        "latency_after_mean",
        "connected",
        "needs_reauth",
        "partial_failures",
        "log_truncated",
    }


def test_route_is_read_only(ctx):
    assert ctx["client"].post(URL).status_code == 405
    assert ctx["client"].put(URL).status_code == 405
    assert ctx["client"].delete(URL).status_code == 405


def test_verdict_requires_authentication():
    app.dependency_overrides.clear()
    assert TestClient(app).get(URL).status_code == 401


def test_services_endpoint_reports_expired_and_skips_malformed_entries(ctx):
    row = _row()
    row.status = "expired"
    row.config = {
        "services": [{"id": SID, "name": "ok"}, {"name": "no id"}, "junk", {"id": 5}]
    }
    ctx["find"].return_value = row
    d = _get(ctx, "/api/v1/render/services")
    assert d["needs_reauth"] is True
    assert [s["id"] for s in d["services"]] == [SID]


def test_services_endpoint_not_connected(ctx):
    ctx["find"].return_value = None
    d = _get(ctx, "/api/v1/render/services")
    assert d["connected"] is False and d["services"] == []


# ── Hard constraint: level survives client -> route -> verdict ───────────


def _wire_real_client(monkeypatch, before_labels, after_labels, ctx):
    """Real fetch_logs/fetch_metric, fake transport: only `_get` is replaced."""
    boundary = rc._iso(CREATED)

    def _payload(level_for):
        def _e(level):
            labels = [] if level is None else [{"name": "level", "value": level}]
            return {
                "timestamp": "2026-10-19T06:01:00Z",
                "message": "m",
                "labels": labels,
            }

        return {"logs": [_e(lv) for lv in level_for], "hasMore": False}

    async def _fake_get(client, path, api_key, params=None):
        if path == "/logs":
            return _payload(
                before_labels if params["startTime"] < boundary else after_labels
            )
        return []

    monkeypatch.setattr(rc, "_get", _fake_get)
    monkeypatch.setattr(route, "_fetch_logs", _real_fetch_logs)
    monkeypatch.setattr(route, "_fetch_metric", _real_fetch_metric)


async def _real_fetch_logs(service_id, owner_id, start, end, api_key, http):
    return await rc.fetch_logs(service_id, owner_id, start, end, api_key, http)


async def _real_fetch_metric(service_id, start, end, metric, api_key, http):
    return await rc.fetch_metric(service_id, start, end, metric, api_key, http)


def test_level_flows_from_render_payload_to_verdict(ctx, monkeypatch):
    _wire_real_client(
        monkeypatch,
        before_labels=["error"] * 2 + ["info"] * 8,
        after_labels=["error"] * 10 + ["info"] * 2,
        ctx=ctx,
    )
    d = _get(ctx)
    assert (d["before_error_count"], d["after_error_count"]) == (2, 10)
    assert d["verdict"] == "regression"


def test_dropping_the_level_label_cannot_yield_a_clean_verdict(ctx, monkeypatch):
    _wire_real_client(
        monkeypatch,
        before_labels=[None] * 8,
        after_labels=[None] * 8,
        ctx=ctx,
    )
    d = _get(ctx)
    assert d["verdict"] == "unknown"
    assert "log_level_unavailable_before" in d["partial_failures"]
    assert "log_level_unavailable_after" in d["partial_failures"]


def test_info_only_payload_counts_zero_errors(ctx, monkeypatch):
    _wire_real_client(
        monkeypatch, before_labels=["info"] * 6, after_labels=["info"] * 6, ctx=ctx
    )
    d = _get(ctx)
    assert d["before_error_count"] == d["after_error_count"] == 0
    # The wired metrics return no points, so the verdict cannot claim neutral.
    assert d["verdict"] == "unknown"
