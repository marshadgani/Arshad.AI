"""API tests for FEAT-167 — GET /api/v1/ontology/entities and
PATCH /api/v1/ontology/entities/visibility.

Auth and DB are overridden; the service / query helper are patched so no
Postgres is needed. Real SQL behaviour is covered in the pg test module.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.database import get_db
from src.models.user import User
from src.services.ingestion.ontology_visibility import EntityNotFoundError

URL_LIST = "/api/v1/ontology/entities"
URL_PATCH = "/api/v1/ontology/entities/visibility"
SERVICE = "src.api.v1.ontology.set_entity_visibility"
FETCH = "src.api.v1.ontology._fetch_entities"


@pytest.fixture
def ctx():
    user = User(id=uuid.uuid4(), email="vis@example.com", name="Vis User")
    db = AsyncMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app, raise_server_exceptions=False), user, db
    app.dependency_overrides.clear()


def _row(key="alice-gh", etype="person", vis="private"):
    return {
        "id": uuid.uuid4(),
        "entity_type": etype,
        "external_key": key,
        "visibility": vis,
    }


def _patch(c, ids, visibility="public", **extra):
    return c.patch(
        URL_PATCH,
        json={"ids": [str(i) for i in ids], "visibility": visibility, **extra},
    )


# ── auth ─────────────────────────────────────────────────────────────────────


def test_get_requires_auth():
    resp = TestClient(app, raise_server_exceptions=False).get(URL_LIST)
    assert resp.status_code == 401


def test_patch_requires_auth_and_never_reaches_service():
    c = TestClient(app, raise_server_exceptions=False)
    with patch(SERVICE, new_callable=AsyncMock) as svc:
        resp = _patch(c, [uuid.uuid4()])
    assert resp.status_code == 401
    svc.assert_not_awaited()


# ── GET ──────────────────────────────────────────────────────────────────────


def test_get_returns_data_envelope_with_total(ctx):
    c, _, _ = ctx
    rows = [_row(), _row("proj", "project", "public")]
    with patch(FETCH, new_callable=AsyncMock, return_value=(rows, 2)):
        resp = c.get(URL_LIST)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    assert [e["external_key"] for e in data["entities"]] == ["alice-gh", "proj"]
    assert set(data["entities"][0]) == {
        "id",
        "entity_type",
        "external_key",
        "visibility",
    }


def test_get_scopes_query_to_authenticated_user_with_defaults(ctx):
    c, user, db = ctx
    with patch(FETCH, new_callable=AsyncMock, return_value=([], 0)) as fetch:
        assert c.get(URL_LIST).status_code == 200
    assert fetch.await_args.args == (db, user.id, None, None, 20, 0)


def test_get_passes_filters_and_paging_through(ctx):
    c, user, db = ctx
    with patch(FETCH, new_callable=AsyncMock, return_value=([], 0)) as fetch:
        resp = c.get(f"{URL_LIST}?type=project&visibility=public&limit=100&offset=40")
    assert resp.status_code == 200
    assert fetch.await_args.args == (db, user.id, "project", "public", 100, 40)


@pytest.mark.parametrize(
    "qs",
    [
        "limit=101",
        "limit=0",
        "limit=-1",
        "offset=-1",
        "type=event",
        "visibility=secret",
        "limit=abc",
    ],
)
def test_get_rejects_invalid_query_params(ctx, qs):
    c, _, _ = ctx
    with patch(FETCH, new_callable=AsyncMock, return_value=([], 0)) as fetch:
        resp = c.get(f"{URL_LIST}?{qs}")
    assert resp.status_code == 422
    fetch.assert_not_awaited()


def test_get_response_rejects_unexpected_visibility_values_from_db(ctx):
    # response_model is Literal-typed: a corrupted row must not be served as-is.
    c, _, _ = ctx
    with patch(FETCH, new_callable=AsyncMock, return_value=([_row(vis="internal")], 1)):
        resp = c.get(URL_LIST)
    assert resp.status_code == 500


# ── PATCH: validation ────────────────────────────────────────────────────────


def test_patch_accepts_exactly_200_ids(ctx):
    c, _, _ = ctx
    with patch(
        SERVICE, new_callable=AsyncMock, return_value={"updated": 200, "unchanged": 0}
    ):
        resp = _patch(c, [uuid.uuid4() for _ in range(200)])
    assert resp.status_code == 200
    assert resp.json() == {"data": {"updated": 200, "unchanged": 0}}


def test_patch_201_ids_is_422_and_service_not_called(ctx):
    c, _, _ = ctx
    ids = [uuid.uuid4() for _ in range(201)]
    with patch(SERVICE, new_callable=AsyncMock) as svc:
        resp = _patch(c, ids)
    assert resp.status_code == 422
    svc.assert_not_awaited()
    assert not any(str(i) in resp.text for i in ids[:5]), (
        "422 must not echo submitted ids"
    )


@pytest.mark.parametrize(
    "bad", ["unpublished", "PUBLIC", "Private", "1", "", None, True]
)
def test_patch_rejects_values_other_than_public_or_private(ctx, bad):
    c, _, _ = ctx
    with patch(SERVICE, new_callable=AsyncMock) as svc:
        resp = c.patch(URL_PATCH, json={"ids": [str(uuid.uuid4())], "visibility": bad})
    assert resp.status_code == 422
    svc.assert_not_awaited()


@pytest.mark.parametrize(
    "extra",
    [{"user_id": str(uuid.uuid4())}, {"entity_type": "person"}, {"force": True}],
)
def test_patch_rejects_unknown_body_fields(ctx, extra):
    c, _, _ = ctx
    with patch(SERVICE, new_callable=AsyncMock) as svc:
        resp = _patch(c, [uuid.uuid4()], **extra)
    assert resp.status_code == 422
    svc.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"ids": [str(uuid.uuid4())]},
        {"visibility": "public"},
        {"ids": [], "visibility": "public"},
    ],
)
def test_patch_rejects_missing_or_empty_fields(ctx, body):
    c, _, _ = ctx
    assert c.patch(URL_PATCH, json=body).status_code == 422


def test_patch_rejects_non_uuid_ids(ctx):
    c, _, _ = ctx
    with patch(SERVICE, new_callable=AsyncMock) as svc:
        resp = c.patch(URL_PATCH, json={"ids": ["not-a-uuid"], "visibility": "public"})
    assert resp.status_code == 422
    svc.assert_not_awaited()


# ── PATCH: behaviour ─────────────────────────────────────────────────────────


def test_patch_calls_service_with_authenticated_user_and_commits(ctx):
    c, user, db = ctx
    eid = uuid.uuid4()
    with patch(
        SERVICE, new_callable=AsyncMock, return_value={"updated": 1, "unchanged": 0}
    ) as svc:
        resp = _patch(c, [eid], "private")
    assert resp.status_code == 200
    svc.assert_awaited_once_with(db, user.id, [eid], "private")
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


def test_patch_response_contains_only_counts(ctx):
    c, _, _ = ctx
    with patch(
        SERVICE, new_callable=AsyncMock, return_value={"updated": 1, "unchanged": 0}
    ):
        resp = _patch(c, [uuid.uuid4()])
    assert set(resp.json()["data"]) == {"updated", "unchanged"}


def test_patch_not_owned_is_404_rolls_back_and_never_commits(ctx):
    c, _, db = ctx
    foreign = uuid.uuid4()
    with patch(SERVICE, new_callable=AsyncMock, side_effect=EntityNotFoundError("x")):
        resp = _patch(c, [foreign])
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "entity_not_found"
    assert set(body["error"]) == {"code", "message", "details"}
    assert str(foreign) not in resp.text
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


def test_patch_foreign_and_missing_ids_yield_identical_responses(ctx):
    c, _, _ = ctx
    out = []
    with patch(SERVICE, new_callable=AsyncMock, side_effect=EntityNotFoundError("x")):
        for _ in range(2):
            r = _patch(c, [uuid.uuid4()])
            out.append((r.status_code, r.json()))
    assert out[0] == out[1]


def test_patch_unexpected_error_is_500_without_leaking_details_and_never_commits(ctx):
    c, _, db = ctx
    secret = "secret-key-xyz"
    with patch(
        SERVICE, new_callable=AsyncMock, side_effect=RuntimeError(f"near {secret}")
    ):
        resp = _patch(c, [uuid.uuid4()])
    assert resp.status_code == 500
    assert secret not in resp.text
    assert "code" in resp.json()["error"]
    db.commit.assert_not_awaited()


def test_patch_service_value_error_does_not_commit(ctx):
    c, _, db = ctx
    with patch(
        SERVICE, new_callable=AsyncMock, side_effect=ValueError("at most 200 ids")
    ):
        resp = _patch(c, [uuid.uuid4()])
    assert resp.status_code == 500
    db.commit.assert_not_awaited()


def test_patch_database_error_is_structured_409_and_rolls_back(ctx):
    c, _, db = ctx
    err = DBAPIError("UPDATE secret-key-xyz", {}, Exception("trigger said no"))
    with patch(SERVICE, new_callable=AsyncMock, side_effect=err):
        resp = _patch(c, [uuid.uuid4()])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "visibility_update_failed"
    assert "secret-key-xyz" not in resp.text
    db.rollback.assert_awaited()
    db.commit.assert_not_awaited()


def test_patch_commit_failure_is_structured_409_and_rolls_back(ctx):
    c, _, db = ctx
    db.commit.side_effect = DBAPIError("COMMIT", {}, Exception("deadlock"))
    with patch(SERVICE, new_callable=AsyncMock, return_value={"updated": 1, "unchanged": 0}):
        resp = _patch(c, [uuid.uuid4()])
    assert resp.status_code == 409
    db.rollback.assert_awaited()


def test_patch_unexpected_error_rolls_back_before_the_global_handler(ctx):
    c, _, db = ctx
    with patch(SERVICE, new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        resp = _patch(c, [uuid.uuid4()])
    assert resp.status_code == 500
    db.rollback.assert_awaited()
    db.commit.assert_not_awaited()
