"""Defense-in-depth tests: private rows must never reach render or push."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from src.services.ingestion.obsidian_vault_render import (
    Entity,
    Relationship,
    render_vault,
)
from src.services.ingestion.obsidian_vault_repository import (
    fetch_public_entities,
    fetch_public_relationships,
)


async def _insert(session, user_id, etype, key, visibility) -> uuid.UUID:
    eid = uuid.uuid4()
    if visibility == "public":
        await session.execute(text("SET LOCAL app.allow_visibility_promotion = 'true'"))
    await session.execute(
        text(
            "INSERT INTO ontology_entities (id, user_id, entity_type, external_key, visibility) "
            "VALUES (:id, :u, :t, :k, :v)"
        ),
        {"id": eid, "u": user_id, "t": etype, "k": key, "v": visibility},
    )
    await session.flush()
    return eid


async def _insert_rel(session, user_id, src, dst, visibility) -> None:
    if visibility == "public":
        await session.execute(text("SET LOCAL app.allow_visibility_promotion = 'true'"))
    await session.execute(
        text(
            "INSERT INTO ontology_relationships "
            "(id, user_id, source_entity_id, relationship_type, target_entity_id, visibility) "
            "VALUES (:id, :u, :s, 'contributed_to', :t, :v)"
        ),
        {"id": uuid.uuid4(), "u": user_id, "s": src, "t": dst, "v": visibility},
    )
    await session.flush()


@pytest.mark.pg
@pytest.mark.asyncio
async def test_query_layer_excludes_private(pg_session, committed_user) -> None:
    await _insert(pg_session, committed_user.id, "person", "pub", "public")
    await _insert(pg_session, committed_user.id, "person", "priv", "private")
    rows = await fetch_public_entities(pg_session, committed_user.id)
    assert [r["external_key"] for r in rows] == ["pub"]


@pytest.mark.pg
@pytest.mark.asyncio
async def test_private_relationship_excluded(pg_session, committed_user) -> None:
    p = await _insert(pg_session, committed_user.id, "person", "pub", "public")
    j = await _insert(pg_session, committed_user.id, "project", "o/r", "public")
    await _insert_rel(pg_session, committed_user.id, p, j, "private")
    assert await fetch_public_relationships(pg_session, committed_user.id) == []


@pytest.mark.pg
@pytest.mark.asyncio
async def test_public_edge_to_private_endpoint_excluded(
    pg_session, committed_user
) -> None:
    p = await _insert(pg_session, committed_user.id, "person", "pub", "public")
    j = await _insert(pg_session, committed_user.id, "project", "o/secret", "private")
    await _insert_rel(pg_session, committed_user.id, p, j, "public")
    assert await fetch_public_relationships(pg_session, committed_user.id) == []


def test_renderer_layer_blocks_private() -> None:
    with pytest.raises(ValueError):
        render_vault([Entity("1", "person", "hidden", "private")], [])


def test_no_private_key_in_output() -> None:
    ents = [Entity("1", "person", "pub", "public")]
    rels = [Relationship("pub", "person", "private-repo", "project", "contributed_to")]
    files = render_vault(ents, rels)
    blob = "\n".join([*files, *files.values()])
    assert "private-repo" not in blob


def test_stale_files_not_deleted_documented() -> None:
    a = Entity("1", "person", "a", "public")
    b = Entity("2", "person", "b", "public")
    assert len(render_vault([a, b], [])) == 2
    assert len(render_vault([a], [])) == 1
