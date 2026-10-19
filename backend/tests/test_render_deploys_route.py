"""FEAT-132 route tests: always-200 contract, via monkeypatched seams."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.api.v1 import render_deploys as route
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.services.render.models import DeployRecord, LogRecord, MetricWindow

SID = "srv-abc123"
URL = f"/api/v1/render/services/{SID}/deploys/dep-1/verdict"
CREATED = datetime.now(timezone.utc) - timedelta(hours=10)
DEPLOY = DeployRecord(
    service_id=SID,
    deploy_id="dep-1",
    created_at=CREATED,
    finished_at=CREATED + timedelta(minutes=3),
    status="live",
)


class _User:
    id = uuid.uuid4()


def _row(owner="tea-1"):
    row = MagicMock()
    row.status = "connected"
    row.config = {
        "services": [
            {
                "id": SID,
                "name": "api",
                "owner_id": owner,
                "latest_deploy_id": "dep-1",
                "latest_deploy_status": "live",
            }
        ]
    }
    return row


def _logs(n_err=1, n_info=5):
    ts = CREATED
    return [LogRecord(timestamp=ts, level="error", message="e")] * n_err + [
        LogRecord(timestamp=ts, level="info", message="i")
    ] * n_info


@pytest.fixture
def client(monkeypatch):
    db = MagicMock()
    db.rollback = AsyncMock()

    async def _db():
        yield db

    async def _user():
        return _User()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(route, "_check_rate_limit", AsyncMock())
    monkeypatch.setattr(
        route, "_find_render_integration", AsyncMock(return_value=_row())
    )
    monkeypatch.setattr(route, "_get_api_key", AsyncMock(return_value="rnd_key"))
    monkeypatch.setattr(route, "_fetch_deploy_record", AsyncMock(return_value=DEPLOY))
    monkeypatch.setattr(
        route, "_fetch_logs", AsyncMock(return_value=(_logs(), False, None))
    )
    monkeypatch.setattr(
        route,
        "_fetch_metric",
        AsyncMock(return_value=MetricWindow(mean=1.0, sample_count=3)),
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _data(resp):
    assert resp.status_code == 200
    return resp.json()["data"]


def test_happy_path_is_neutral(client):
    d = _data(client.get(URL))
    assert d["verdict"] == "neutral" and d["connected"] is True


def test_render_down_is_200_unknown(monkeypatch, client):
    monkeypatch.setattr(
        route, "_fetch_deploy_record", AsyncMock(side_effect=httpx.ConnectError("x"))
    )
    d = _data(client.get(URL))
    assert d["verdict"] == "unknown" and d["partial_failures"] == ["deploy_record"]


def test_no_integration_is_connected_false(monkeypatch, client):
    monkeypatch.setattr(route, "_find_render_integration", AsyncMock(return_value=None))
    d = _data(client.get(URL))
    assert d["connected"] is False and d["verdict"] == "unknown"


def test_rate_limit_returns_429(monkeypatch, client):
    monkeypatch.setattr(
        route, "_check_rate_limit", AsyncMock(side_effect=HTTPException(429, "slow"))
    )
    assert client.get(URL).status_code == 429


def test_invalid_service_id_is_422(client):
    resp = client.get("/api/v1/render/services/nope/deploys/dep-1/verdict")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_service_id"


@pytest.mark.parametrize(
    "bad", ["garbage!!", "..", ".", "dep-", "srv-abc", "dep-" + "a" * 65, "dep-a%2Fb"]
)
def test_malformed_deploy_id_is_rejected_before_any_render_call(
    monkeypatch, client, bad
):
    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(route, "_fetch_deploy_record", spy)
    resp = client.get(f"/api/v1/render/services/{SID}/deploys/{bad}/verdict")
    assert resp.status_code in (404, 422)
    if resp.status_code == 422:
        assert resp.json()["error"]["code"] == "invalid_deploy_id"
    spy.assert_not_awaited()


def test_well_formed_deploy_id_reaches_render(monkeypatch, client):
    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(route, "_fetch_deploy_record", spy)
    d = _data(client.get(f"/api/v1/render/services/{SID}/deploys/dep-abc123/verdict"))
    assert spy.await_args.args[1] == "dep-abc123"
    assert d["partial_failures"] == ["deploy_record"]


def test_service_not_in_snapshot_is_unknown(client):
    d = _data(client.get("/api/v1/render/services/srv-other/deploys/dep-1/verdict"))
    assert d["partial_failures"] == ["service_not_found"]


def test_metric_failure_named_in_partial_failures(monkeypatch, client):
    monkeypatch.setattr(
        route,
        "_fetch_metric",
        AsyncMock(
            return_value=MetricWindow(fetch_failed=True, failure_code="fetch_error")
        ),
    )
    d = _data(client.get(URL))
    assert {"cpu", "memory", "latency"} <= set(d["partial_failures"])
    assert "scope_insufficient" not in d["partial_failures"]
    assert d["verdict"] == "unknown"


def test_log_truncation_reported(monkeypatch, client):
    monkeypatch.setattr(
        route, "_fetch_logs", AsyncMock(return_value=(_logs(), True, None))
    )
    d = _data(client.get(URL))
    assert d["log_truncated"] is True and d["verdict"] == "unknown"


def test_logs_403_is_scope_insufficient_not_reauth(monkeypatch, client):
    monkeypatch.setattr(
        route, "_fetch_logs", AsyncMock(return_value=([], False, "scope_insufficient"))
    )
    d = _data(client.get(URL))
    assert "scope_insufficient" in d["partial_failures"]
    assert d["needs_reauth"] is False and d["verdict"] == "unknown"


def test_401_sets_needs_reauth(monkeypatch, client):
    monkeypatch.setattr(
        route, "_fetch_logs", AsyncMock(return_value=([], False, "needs_reauth"))
    )
    d = _data(client.get(URL))
    assert d["needs_reauth"] is True and d["verdict"] == "unknown"


def test_owner_id_comes_from_snapshot(monkeypatch, client):
    spy = AsyncMock(return_value=(_logs(), False, None))
    monkeypatch.setattr(route, "_fetch_logs", spy)
    _data(client.get(URL))
    assert spy.await_args_list[0].args[1] == "tea-1"


def test_services_endpoint_hides_owner_id(client):
    d = _data(client.get("/api/v1/render/services"))
    assert d["connected"] is True
    assert d["services"][0]["latest_deploy_id"] == "dep-1"
    assert "owner_id" not in d["services"][0]
