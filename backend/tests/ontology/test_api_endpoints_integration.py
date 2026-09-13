"""Integration tests — the 3 ontology API endpoints.

All tests use FastAPI AsyncClient + test DB.
Auth is mocked by overriding the get_current_user dependency.

Covers TC-050 through TC-066.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.main import app
from src.models.dag_trigger import DagTriggerQueue
from src.models.database import get_db
from src.models.ontology import OntologyEntityNote, OntologySyncRun
from src.models.user import User


@pytest_asyncio.fixture()
def auth_user() -> User:
    u = User()
    u.id = uuid.uuid4()
    u.email = "api_test@example.com"
    return u


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession, auth_user: User):
    app.dependency_overrides[get_current_user] = lambda: auth_user
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── TC-050 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_sync_creates_dag_trigger_job(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """POST /api/v1/obsidian/ontology/sync creates a DagTriggerQueue row with correct dag_id."""
    resp = await client.post("/api/v1/obsidian/ontology/sync", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert "data" in body
    assert "job_id" in body["data"]
    assert body["data"]["status"] == "pending"
    uuid.UUID(body["data"]["job_id"])  # raises if invalid

    row = await db_session.scalar(
        select(DagTriggerQueue).where(
            DagTriggerQueue.dag_id == "obsidian_ontology_sync",
            DagTriggerQueue.user_id == auth_user.id,
        )
    )
    assert row is not None
    assert row.dag_id == "obsidian_ontology_sync"


# ── TC-051 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_sync_persists_domains_filter(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """POST with explicit domains=['calendar'] stores that filter in queued payload."""
    resp = await client.post(
        "/api/v1/obsidian/ontology/sync", json={"domains": ["calendar"]}
    )
    assert resp.status_code == 201
    job_id = resp.json()["data"]["job_id"]
    row = await db_session.scalar(
        select(DagTriggerQueue).where(DagTriggerQueue.id == uuid.UUID(job_id))
    )
    assert row is not None
    assert row.payload.get("domains") == ["calendar"]


# ── TC-052 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_sync_deduplicates_pending_job(client: AsyncClient):
    """Second POST while a pending job exists returns deduplicated=True, no new row."""
    resp1 = await client.post("/api/v1/obsidian/ontology/sync", json={})
    assert resp1.status_code == 201
    resp2 = await client.post("/api/v1/obsidian/ontology/sync", json={})
    assert resp2.status_code == 201
    assert resp2.json()["data"]["deduplicated"] is True
    # Same job_id is returned, not a fresh one.
    assert resp2.json()["data"]["job_id"] == resp1.json()["data"]["job_id"]


# ── TC-053 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_sync_no_auth_returns_401():
    """POST without auth token returns 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/obsidian/ontology/sync", json={})
    assert resp.status_code == 401


# ── TC-054 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_default_pagination(client: AsyncClient):
    """GET /ontology/entities default: limit=20, offset=0, returns {data: [...], total: N}."""
    resp = await client.get("/api/v1/obsidian/ontology/entities")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "total" in body
    assert isinstance(body["data"], list)
    assert len(body["data"]) <= 20


# ── TC-055 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_max_limit_clamped(client: AsyncClient):
    """GET with limit=9999 must be rejected (FastAPI le=100 constraint) as 422,
    never silently clamped and served as 200 — that would be a boundary-
    validation gap letting an unbounded query slip through the API layer."""
    resp = await client.get("/api/v1/obsidian/ontology/entities?limit=9999")
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body or "error" in body


# ── TC-055b ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_limit_at_max_boundary_succeeds(client: AsyncClient):
    """limit=100 (the documented max) must be accepted, not rejected."""
    resp = await client.get("/api/v1/obsidian/ontology/entities?limit=100")
    assert resp.status_code == 200


# ── TC-055c ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_negative_offset_rejected(client: AsyncClient):
    """offset below 0 must 422, not wrap or be sent to Postgres as-is."""
    resp = await client.get("/api/v1/obsidian/ontology/entities?offset=-1")
    assert resp.status_code == 422


# ── TC-056 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_filter_by_domain(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """GET ?domain=calendar returns only calendar entities."""
    for domain, eid in [
        ("calendar", "event:filter_001"),
        ("email", "thread:filter_001"),
    ]:
        row = OntologyEntityNote()
        row.id = uuid.uuid4()
        row.user_id = auth_user.id
        row.domain = domain
        row.entity_type = "Event" if domain == "calendar" else "Thread"
        row.stable_entity_id = eid
        row.display_name = f"{domain} entity"
        row.vault_path = f"entities/{domain}/type/{eid}.md"
        db_session.add(row)
    await db_session.flush()

    resp = await client.get("/api/v1/obsidian/ontology/entities?domain=calendar")
    assert resp.status_code == 200
    entities = resp.json()["data"]
    assert all(e["domain"] == "calendar" for e in entities)
    assert any(e["stable_entity_id"] == "event:filter_001" for e in entities)


# ── TC-057 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_response_shape(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """Each entity in the list has the documented fields; no internal fields leaked."""
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = auth_user.id
    row.domain = "calendar"
    row.entity_type = "Event"
    row.stable_entity_id = "event:shape_001"
    row.display_name = "Shape Test"
    row.vault_path = "entities/calendar/Event/event:shape_001.md"
    db_session.add(row)
    await db_session.flush()

    resp = await client.get("/api/v1/obsidian/ontology/entities")
    entity = next(
        (e for e in resp.json()["data"] if e["stable_entity_id"] == "event:shape_001"),
        None,
    )
    assert entity is not None
    for field in (
        "id",
        "domain",
        "entity_type",
        "stable_entity_id",
        "display_name",
        "vault_path",
        "sync_state",
        "tags",
    ):
        assert field in entity
    # Internal fields must not be present
    assert "frontmatter_json" not in entity
    assert "relationships" not in entity


# ── TC-058 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_status_zero_rows_fresh_user(client: AsyncClient):
    """GET /ontology/status with no rows returns zeroed counts and null last_run_at."""
    resp = await client.get("/api/v1/obsidian/ontology/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_entities"] == 0
    assert data["last_run_at"] is None
    assert data["last_commit_sha"] is None
    assert data["deferred"] == 0
    assert data["conflicts"] == 0


# ── TC-059 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_status_counts_by_domain(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """GET /ontology/status aggregates entity_counts_by_domain correctly."""
    for i in range(3):
        row = OntologyEntityNote()
        row.id = uuid.uuid4()
        row.user_id = auth_user.id
        row.domain = "calendar"
        row.entity_type = "Event"
        row.stable_entity_id = f"event:status_{i}"
        row.display_name = f"Event {i}"
        row.vault_path = f"entities/calendar/Event/event:status_{i}.md"
        db_session.add(row)
    await db_session.flush()

    resp = await client.get("/api/v1/obsidian/ontology/status")
    data = resp.json()["data"]
    assert data["entity_counts_by_domain"].get("calendar", 0) >= 3


# ── TC-060 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_status_deferred_count(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """GET /ontology/status deferred count reflects sync_state='deferred' rows."""
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = auth_user.id
    row.domain = "calendar"
    row.entity_type = "Event"
    row.stable_entity_id = "event:deferred_001"
    row.display_name = "Deferred Event"
    row.vault_path = "entities/calendar/Event/event:deferred_001.md"
    row.sync_state = "deferred"
    db_session.add(row)
    await db_session.flush()

    resp = await client.get("/api/v1/obsidian/ontology/status")
    data = resp.json()["data"]
    assert data["deferred"] >= 1


# ── TC-061 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_status_includes_last_run_from_sync_runs(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """last_run_at and last_commit_sha come from OntologySyncRun, not from entity rows."""
    run = OntologySyncRun()
    run.id = uuid.uuid4()
    run.user_id = auth_user.id
    run.status = "succeeded"
    run.commit_sha = "abc1234"
    run.branch = "main"
    db_session.add(run)
    await db_session.flush()

    resp = await client.get("/api/v1/obsidian/ontology/status")
    data = resp.json()["data"]
    assert data["last_run_at"] is not None
    assert data["last_commit_sha"] == "abc1234"


# ── TC-062 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_filter_by_sync_state(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """GET ?sync_state=synced returns only synced entities."""
    for state, eid in [("synced", "event:sync_001"), ("pending", "event:pend_001")]:
        row = OntologyEntityNote()
        row.id = uuid.uuid4()
        row.user_id = auth_user.id
        row.domain = "calendar"
        row.entity_type = "Event"
        row.stable_entity_id = eid
        row.display_name = f"{state} entity"
        row.vault_path = f"entities/calendar/Event/{eid}.md"
        row.sync_state = state
        db_session.add(row)
    await db_session.flush()

    resp = await client.get("/api/v1/obsidian/ontology/entities?sync_state=synced")
    assert resp.status_code == 200
    entities = resp.json()["data"]
    assert all(e["sync_state"] == "synced" for e in entities)


# ── TC-063 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_no_auth_returns_401():
    """GET /ontology/entities without auth returns 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/obsidian/ontology/entities")
    assert resp.status_code == 401


# ── TC-064 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_status_no_auth_returns_401():
    """GET /ontology/status without auth returns 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/obsidian/ontology/status")
    assert resp.status_code == 401


# ── TC-065 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_sync_lookback_days_validation(client: AsyncClient):
    """lookback_days below minimum (< 1) should return 422."""
    resp = await client.post(
        "/api/v1/obsidian/ontology/sync", json={"lookback_days": 0}
    )
    assert resp.status_code == 422


# ── TC-066 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_sync_max_entities_validation(client: AsyncClient):
    """max_entities above 5000 must return 422."""
    resp = await client.post(
        "/api/v1/obsidian/ontology/sync", json={"max_entities": 9999}
    )
    assert resp.status_code == 422


# ── TC-066b ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_sync_unknown_domain_silently_filtered_not_500(
    client: AsyncClient,
):
    """A domain name the config doesn't recognise must not 500 — the job is
    still queued (config-level filtering happens at consume time, not the
    trigger endpoint), and the raw payload is preserved for audit."""
    resp = await client.post(
        "/api/v1/obsidian/ontology/sync", json={"domains": ["not_a_real_domain"]}
    )
    assert resp.status_code == 201


# ── TC-066c ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ontology_entities_pagination_offset_advances(
    client: AsyncClient, db_session: AsyncSession, auth_user: User
):
    """offset actually skips rows rather than being ignored."""
    for i in range(5):
        row = OntologyEntityNote()
        row.id = uuid.uuid4()
        row.user_id = auth_user.id
        row.domain = "calendar"
        row.entity_type = "Event"
        row.stable_entity_id = f"event:page_{i}"
        row.display_name = f"Page Event {i}"
        row.vault_path = f"entities/calendar/Event/event:page_{i}.md"
        db_session.add(row)
    await db_session.flush()

    first_page = (
        await client.get("/api/v1/obsidian/ontology/entities?limit=2&offset=0")
    ).json()["data"]
    second_page = (
        await client.get("/api/v1/obsidian/ontology/entities?limit=2&offset=2")
    ).json()["data"]
    first_ids = {e["id"] for e in first_page}
    second_ids = {e["id"] for e in second_page}
    assert first_ids.isdisjoint(second_ids)
