"""Postgres integration tests for FEAT-167 (need TEST_DATABASE_URL, mark: pg).

Note on pg_session: it wraps each test in one outer transaction, so a
transaction-local GUC set by the service stays set for the rest of the test.
Tests therefore never assert "GUC cleared" through pg_session; the leak proofs
use their own engine and a real COMMIT / ROLLBACK (see the *_leak tests).
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from src.api.v1.ontology import _fetch_entities
from src.models.user import User
from src.services.ingestion import obsidian_vault_repository as repo
from src.services.ingestion.ontology_visibility import (
    EntityNotFoundError,
    set_entity_visibility,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.pg]

GUC = "app.allow_visibility_promotion"


async def _seed_entity(
    s: AsyncSession,
    uid: uuid.UUID,
    key: str,
    etype: str = "person",
    public: bool = False,
) -> uuid.UUID:
    eid = uuid.uuid4()
    await s.execute(
        text(
            "INSERT INTO ontology_entities (id, user_id, entity_type, external_key, visibility)"
            " VALUES (:id, :uid, :et, :ek, 'private')"
        ),
        {"id": eid, "uid": uid, "et": etype, "ek": key},
    )
    if public:
        await _force_public(s, "ontology_entities", eid)
    return eid


async def _seed_rel(
    s: AsyncSession,
    uid: uuid.UUID,
    src: uuid.UUID,
    dst: uuid.UUID,
    public: bool = False,
) -> uuid.UUID:
    rid = uuid.uuid4()
    await s.execute(
        text(
            "INSERT INTO ontology_relationships"
            " (id, user_id, source_entity_id, relationship_type, target_entity_id, visibility)"
            " VALUES (:id, :uid, :s, 'contributed_to', :t, 'private')"
        ),
        {"id": rid, "uid": uid, "s": src, "t": dst},
    )
    if public:
        await _force_public(s, "ontology_relationships", rid)
    return rid


async def _force_public(s: AsyncSession, table: str, row_id: uuid.UUID) -> None:
    """Test-only promotion that restores the GUC to 'false' afterwards, so the
    code under test is exercised with the promotion gate genuinely closed."""
    await s.execute(text(f"SELECT set_config('{GUC}', 'true', true)"))
    await s.execute(
        text(f"UPDATE {table} SET visibility='public' WHERE id=:id"), {"id": row_id}
    )
    await s.execute(text(f"SELECT set_config('{GUC}', 'false', true)"))


async def _vis(s: AsyncSession, table: str, row_id: uuid.UUID) -> str:
    return (
        await s.execute(
            text(f"SELECT visibility FROM {table} WHERE id=:id"), {"id": row_id}
        )
    ).scalar_one()


async def _other_user(s: AsyncSession, tag: str) -> User:
    u = User(
        id=uuid.uuid4(), email=f"{tag}-{uuid.uuid4().hex[:8]}@example.com", name=tag
    )
    s.add(u)
    await s.flush()
    return u


# ── promotion / demotion against the real trigger ────────────────────────────


async def test_promotion_via_service_passes_trigger(pg_session, committed_user):
    eid = await _seed_entity(pg_session, committed_user.id, "p1")
    result = await set_entity_visibility(pg_session, committed_user.id, [eid], "public")
    assert result == {"updated": 1, "unchanged": 0}
    assert await _vis(pg_session, "ontology_entities", eid) == "public"


async def test_demotion_works_with_promotion_gate_closed(pg_session, committed_user):
    eid = await _seed_entity(pg_session, committed_user.id, "p1", public=True)
    gate = (
        await pg_session.execute(text(f"SELECT current_setting('{GUC}', true)"))
    ).scalar()
    assert gate == "false"
    result = await set_entity_visibility(
        pg_session, committed_user.id, [eid], "private"
    )
    assert result == {"updated": 1, "unchanged": 0}
    assert await _vis(pg_session, "ontology_entities", eid) == "private"


async def test_repeat_promotion_is_idempotent(pg_session, committed_user):
    eid = await _seed_entity(pg_session, committed_user.id, "p1")
    await set_entity_visibility(pg_session, committed_user.id, [eid], "public")
    again = await set_entity_visibility(pg_session, committed_user.id, [eid], "public")
    assert again == {"updated": 0, "unchanged": 1}


# ── relationship derivation ──────────────────────────────────────────────────


@pytest.mark.parametrize("first", ["person", "project"])
async def test_edge_promotes_only_once_both_endpoints_public_in_either_order(
    pg_session, committed_user, first
):
    uid = committed_user.id
    a = await _seed_entity(pg_session, uid, "a", "person")
    b = await _seed_entity(pg_session, uid, "b", "project")
    rel = await _seed_rel(pg_session, uid, a, b)
    one, two = (a, b) if first == "person" else (b, a)

    await set_entity_visibility(pg_session, uid, [one], "public")
    assert await _vis(pg_session, "ontology_relationships", rel) == "private"
    await set_entity_visibility(pg_session, uid, [two], "public")
    assert await _vis(pg_session, "ontology_relationships", rel) == "public"


async def test_promoting_both_in_one_call_promotes_edge(pg_session, committed_user):
    uid = committed_user.id
    a = await _seed_entity(pg_session, uid, "a", "person")
    b = await _seed_entity(pg_session, uid, "b", "project")
    rel = await _seed_rel(pg_session, uid, a, b)
    await set_entity_visibility(pg_session, uid, [a, b], "public")
    assert await _vis(pg_session, "ontology_relationships", rel) == "public"


async def test_promotion_leaves_edges_to_private_neighbours_private(
    pg_session, committed_user
):
    uid = committed_user.id
    a = await _seed_entity(pg_session, uid, "a", "person")
    pub = await _seed_entity(pg_session, uid, "pub", "project", public=True)
    priv = await _seed_entity(pg_session, uid, "priv", "project")
    r_pub = await _seed_rel(pg_session, uid, a, pub)
    r_priv = await _seed_rel(pg_session, uid, a, priv)
    await set_entity_visibility(pg_session, uid, [a], "public")
    assert await _vis(pg_session, "ontology_relationships", r_pub) == "public"
    assert await _vis(pg_session, "ontology_relationships", r_priv) == "private"


async def test_demoting_endpoint_demotes_every_touching_edge_but_not_neighbours(
    pg_session, committed_user
):
    uid = committed_user.id
    a = await _seed_entity(pg_session, uid, "a", "person", public=True)
    b = await _seed_entity(pg_session, uid, "b", "project", public=True)
    c = await _seed_entity(pg_session, uid, "c", "project", public=True)
    ab = await _seed_rel(pg_session, uid, a, b, public=True)
    ac = await _seed_rel(pg_session, uid, a, c, public=True)
    await set_entity_visibility(pg_session, uid, [a], "private")
    assert await _vis(pg_session, "ontology_relationships", ab) == "private"
    assert await _vis(pg_session, "ontology_relationships", ac) == "private"
    assert await _vis(pg_session, "ontology_entities", b) == "public"
    assert await _vis(pg_session, "ontology_entities", c) == "public"


async def test_demoting_target_endpoint_also_demotes_incoming_edge(
    pg_session, committed_user
):
    uid = committed_user.id
    a = await _seed_entity(pg_session, uid, "a", "person", public=True)
    b = await _seed_entity(pg_session, uid, "b", "project", public=True)
    rel = await _seed_rel(pg_session, uid, a, b, public=True)
    await set_entity_visibility(pg_session, uid, [b], "private")
    assert await _vis(pg_session, "ontology_relationships", rel) == "private"


async def test_already_public_endpoints_with_private_edge_is_repaired(
    pg_session, committed_user
):
    uid = committed_user.id
    a = await _seed_entity(pg_session, uid, "a", "person", public=True)
    b = await _seed_entity(pg_session, uid, "b", "project", public=True)
    rel = await _seed_rel(
        pg_session, uid, a, b
    )  # inconsistent: private edge, public ends
    result = await set_entity_visibility(pg_session, uid, [a], "public")
    assert result == {"updated": 0, "unchanged": 1}
    assert await _vis(pg_session, "ontology_relationships", rel) == "public"


async def test_no_public_edge_ever_touches_a_private_entity_after_any_change(
    pg_session, committed_user
):
    uid = committed_user.id
    ents = [await _seed_entity(pg_session, uid, f"p{i}", "person") for i in range(3)]
    projs = [await _seed_entity(pg_session, uid, f"r{i}", "project") for i in range(3)]
    for p in ents:
        for r in projs:
            await _seed_rel(pg_session, uid, p, r)
    await set_entity_visibility(pg_session, uid, ents + projs, "public")
    await set_entity_visibility(pg_session, uid, [ents[0], projs[1]], "private")
    bad = (
        await pg_session.execute(
            text(
                "SELECT count(*) FROM ontology_relationships r WHERE r.user_id=:u"
                " AND r.visibility='public' AND EXISTS (SELECT 1 FROM ontology_entities e"
                " WHERE e.id IN (r.source_entity_id, r.target_entity_id) AND e.visibility='private')"
            ),
            {"u": uid},
        )
    ).scalar_one()
    assert bad == 0


# ── tenant isolation ─────────────────────────────────────────────────────────


async def test_other_users_entity_is_rejected_and_untouched(pg_session, committed_user):
    bob = await _other_user(pg_session, "bob")
    bob_e = await _seed_entity(pg_session, bob.id, "bob-key", public=True)
    with pytest.raises(EntityNotFoundError):
        await set_entity_visibility(pg_session, committed_user.id, [bob_e], "private")
    assert await _vis(pg_session, "ontology_entities", bob_e) == "public"


async def test_foreign_and_missing_ids_raise_identical_errors(
    pg_session, committed_user
):
    bob = await _other_user(pg_session, "bob")
    bob_e = await _seed_entity(pg_session, bob.id, "bob-key")
    errs = []
    for eid in (bob_e, uuid.uuid4()):
        with pytest.raises(EntityNotFoundError) as exc:
            await set_entity_visibility(pg_session, committed_user.id, [eid], "public")
        errs.append((type(exc.value), str(exc.value)))
    assert errs[0] == errs[1]


async def test_mixed_batch_is_all_or_nothing(pg_session, committed_user):
    uid = committed_user.id
    mine = await _seed_entity(pg_session, uid, "mine")
    bob = await _other_user(pg_session, "bob")
    theirs = await _seed_entity(pg_session, bob.id, "theirs")
    with pytest.raises(EntityNotFoundError):
        await set_entity_visibility(pg_session, uid, [mine, theirs], "public")
    assert await _vis(pg_session, "ontology_entities", mine) == "private"
    assert await _vis(pg_session, "ontology_entities", theirs) == "private"


async def test_derivation_never_touches_another_users_edges(pg_session, committed_user):
    uid = committed_user.id
    bob = await _other_user(pg_session, "bob")
    a = await _seed_entity(pg_session, uid, "a", "person", public=True)
    b = await _seed_entity(pg_session, uid, "b", "project", public=True)
    await _seed_rel(pg_session, uid, a, b, public=True)
    ba = await _seed_entity(pg_session, bob.id, "a", "person", public=True)
    bb = await _seed_entity(pg_session, bob.id, "b", "project", public=True)
    bob_rel = await _seed_rel(pg_session, bob.id, ba, bb, public=True)
    await set_entity_visibility(pg_session, uid, [a], "private")
    assert await _vis(pg_session, "ontology_relationships", bob_rel) == "public"
    assert await _vis(pg_session, "ontology_entities", ba) == "public"


# ── GUC lifetime (own engine, real commit/rollback, same pooled connection) ──


async def _engine():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL not set")
    return create_async_engine(
        dsn, pool_size=1, max_overflow=0, connect_args={"statement_cache_size": 0}
    )


async def _guc_on_reused_connection(engine) -> str | None:
    async with engine.connect() as conn:
        return (
            await conn.execute(text(f"SELECT current_setting('{GUC}', true)"))
        ).scalar()


async def _create_user_and_entity(engine) -> tuple[uuid.UUID, uuid.UUID]:
    uid, eid = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, email, name) VALUES (:i, :e, 'guc')"),
            {"i": uid, "e": f"guc-{uid.hex[:8]}@example.com"},
        )
        await conn.execute(
            text(
                "INSERT INTO ontology_entities (id, user_id, entity_type, external_key, visibility)"
                " VALUES (:i, :u, 'person', 'guc-key', 'private')"
            ),
            {"i": eid, "u": uid},
        )
    return uid, eid


async def _drop_user(engine, uid: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})


async def test_guc_not_left_set_after_service_commit():
    engine = await _engine()
    uid, eid = await _create_user_and_entity(engine)
    try:
        async with AsyncSession(engine) as session:
            await set_entity_visibility(session, uid, [eid], "public")
            inside = (
                await session.execute(text(f"SELECT current_setting('{GUC}', true)"))
            ).scalar()
            assert inside == "true"  # the promotion really ran under the gate
            await session.commit()
        assert await _guc_on_reused_connection(engine) != "true"
        async with AsyncSession(engine) as s2:  # promotion persisted
            assert await _vis(s2, "ontology_entities", eid) == "public"
    finally:
        await _drop_user(engine, uid)
        await engine.dispose()


async def test_guc_not_left_set_after_service_rollback():
    engine = await _engine()
    uid, eid = await _create_user_and_entity(engine)
    try:
        async with AsyncSession(engine) as session:
            await set_entity_visibility(session, uid, [eid], "public")
            await session.rollback()
        assert await _guc_on_reused_connection(engine) != "true"
        async with AsyncSession(engine) as s2:
            assert await _vis(s2, "ontology_entities", eid) == "private"
    finally:
        await _drop_user(engine, uid)
        await engine.dispose()


async def test_guc_not_set_by_rejected_or_demotion_calls():
    engine = await _engine()
    uid, eid = await _create_user_and_entity(engine)
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(EntityNotFoundError):
                await set_entity_visibility(session, uid, [uuid.uuid4()], "public")
            assert (
                await session.execute(text(f"SELECT current_setting('{GUC}', true)"))
            ).scalar() != "true"
            await set_entity_visibility(session, uid, [eid], "private")
            assert (
                await session.execute(text(f"SELECT current_setting('{GUC}', true)"))
            ).scalar() != "true"
            await session.rollback()
    finally:
        await _drop_user(engine, uid)
        await engine.dispose()


async def test_bare_promotion_after_a_committed_promotion_is_still_rejected():
    engine = await _engine()
    uid, eid = await _create_user_and_entity(engine)
    e2 = uuid.uuid4()
    try:
        async with AsyncSession(engine) as session:
            await set_entity_visibility(session, uid, [eid], "public")
            await session.commit()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ontology_entities (id, user_id, entity_type, external_key, visibility)"
                    " VALUES (:i, :u, 'project', 'second', 'private')"
                ),
                {"i": e2, "u": uid},
            )
        with pytest.raises(Exception, match="(?i)promotion|explicit"):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE ontology_entities SET visibility='public' WHERE id=:i"
                    ),
                    {"i": e2},
                )
    finally:
        await _drop_user(engine, uid)
        await engine.dispose()


# ── list query + vault integration ───────────────────────────────────────────


async def test_list_query_scopes_filters_orders_and_paginates(
    pg_session, committed_user
):
    uid = committed_user.id
    bob = await _other_user(pg_session, "bob")
    await _seed_entity(pg_session, bob.id, "bob-secret", "person", public=True)
    await _seed_entity(pg_session, uid, "a-person", "person")
    await _seed_entity(pg_session, uid, "b-person", "person", public=True)
    await _seed_entity(pg_session, uid, "c-proj", "project")

    rows, total = await _fetch_entities(pg_session, uid, None, None, 20, 0)
    assert total == 3 and "bob-secret" not in {r["external_key"] for r in rows}
    assert [r["external_key"] for r in rows] == ["a-person", "b-person", "c-proj"]

    rows, total = await _fetch_entities(pg_session, uid, "person", "public", 20, 0)
    assert (total, [r["external_key"] for r in rows]) == (1, ["b-person"])

    rows, total = await _fetch_entities(pg_session, uid, None, None, 2, 2)
    assert total == 3 and [r["external_key"] for r in rows] == ["c-proj"]

    rows, total = await _fetch_entities(pg_session, uid, None, None, 20, 50)
    assert total == 3 and rows == []


async def test_vault_layer_sees_exactly_what_the_service_published(
    pg_session, committed_user
):
    uid = committed_user.id
    a = await _seed_entity(pg_session, uid, "vault-a", "person")
    b = await _seed_entity(pg_session, uid, "vault-b", "project")
    await _seed_rel(pg_session, uid, a, b)
    assert await repo.fetch_public_entities(pg_session, uid) == []

    await set_entity_visibility(pg_session, uid, [a, b], "public")
    assert {
        e["external_key"] for e in await repo.fetch_public_entities(pg_session, uid)
    } == {
        "vault-a",
        "vault-b",
    }
    rels = await repo.fetch_public_relationships(pg_session, uid)
    assert [(r["source_key"], r["target_key"]) for r in rels] == [
        ("vault-a", "vault-b")
    ]

    await set_entity_visibility(pg_session, uid, [a], "private")
    assert {
        e["external_key"] for e in await repo.fetch_public_entities(pg_session, uid)
    } == {"vault-b"}
    assert await repo.fetch_public_relationships(pg_session, uid) == []
