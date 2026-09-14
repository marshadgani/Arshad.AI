"""Security tests — visibility-ratchet trigger on ontology_entities and
ontology_relationships, CHECK constraints (BLOCKER 2 scope guard), and
composite FK tenant-integrity enforcement.

All tests require real Postgres (@pytest.mark.pg, pg_session fixture from
backend/tests/conftest.py).  The trigger is PL/pgSQL — it cannot be faked,
mocked, or run against SQLite/in-memory.

HIGH 1 (FEAT-144 retry): test_bare_update_rejects_visibility_promotion is
the PRIMARY regression test mandated by the requirement.  It must never be
skipped.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

# ── GUC helpers ───────────────────────────────────────────────────────────────


async def _assert_promotion_guc_clear(session: AsyncSession) -> None:
    result = await session.execute(
        text("SELECT current_setting('app.allow_visibility_promotion', true)")
    )
    val = result.scalar()
    assert val != "true", (
        f"GUC app.allow_visibility_promotion leaked from a previous test: {val!r}. "
        "Check teardown in conftest.pg_connection fixture."
    )


async def _set_promotion_guc(session: AsyncSession) -> None:
    await session.execute(text("SET LOCAL app.allow_visibility_promotion = 'true'"))


# ── Entity factory helpers ─────────────────────────────────────────────────────


async def _insert_entity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    entity_type: str = "person",
    external_key: str = "alice",
    visibility: str = "private",
    set_guc: bool = False,
) -> uuid.UUID:
    if set_guc:
        await _set_promotion_guc(session)
    entity_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO ontology_entities "
            "(id, user_id, entity_type, external_key, visibility) "
            "VALUES (:id, :user_id, :entity_type, :external_key, :visibility)"
        ),
        {
            "id": entity_id,
            "user_id": user_id,
            "entity_type": entity_type,
            "external_key": external_key,
            "visibility": visibility,
        },
    )
    await session.flush()
    return entity_id


# ── HIGH 1 — PRIMARY regression test ─────────────────────────────────────────


@pytest.mark.pg
async def test_bare_update_rejects_visibility_promotion(
    pg_session: AsyncSession, committed_user
) -> None:
    """HIGH 1 from FEAT-144 retry.

    A bare 'UPDATE ontology_entities SET visibility='public'' with no GUC set
    must be rejected by the visibility-ratchet trigger.
    """
    await _assert_promotion_guc_clear(pg_session)

    entity_id = await _insert_entity(pg_session, user_id=committed_user.id)

    with pytest.raises((StatementError, DBAPIError, ProgrammingError)) as exc_info:
        await pg_session.execute(
            text("UPDATE ontology_entities SET visibility = 'public' WHERE id = :id"),
            {"id": entity_id},
        )
        await pg_session.flush()

    err_msg = str(exc_info.value).lower()
    assert "promotion" in err_msg or "explicit" in err_msg or "ratchet" in err_msg, (
        f"Expected trigger error referencing promotion guard, got: {exc_info.value}"
    )


# ── INSERT-arm companion ───────────────────────────────────────────────────────


@pytest.mark.pg
async def test_insert_with_public_visibility_rejected_without_guc(
    pg_session: AsyncSession, committed_user
) -> None:
    await _assert_promotion_guc_clear(pg_session)

    with pytest.raises((StatementError, DBAPIError, ProgrammingError)) as exc_info:
        await _insert_entity(
            pg_session,
            user_id=committed_user.id,
            visibility="public",
            set_guc=False,
        )

    err_msg = str(exc_info.value).lower()
    assert "promotion" in err_msg or "explicit" in err_msg or "ratchet" in err_msg


# ── NULL-laundering ───────────────────────────────────────────────────────────


@pytest.mark.pg
async def test_null_laundering_rejected(
    pg_session: AsyncSession, committed_user
) -> None:
    await _assert_promotion_guc_clear(pg_session)

    entity_id = await _insert_entity(
        pg_session, user_id=committed_user.id, visibility="private"
    )

    with pytest.raises((StatementError, DBAPIError, ProgrammingError)):
        await pg_session.execute(
            text("UPDATE ontology_entities SET visibility = NULL WHERE id = :id"),
            {"id": entity_id},
        )
        await pg_session.flush()


# ── Positive control ──────────────────────────────────────────────────────────


@pytest.mark.pg
async def test_promotion_succeeds_with_guc_set(
    pg_session: AsyncSession, committed_user
) -> None:
    await _assert_promotion_guc_clear(pg_session)

    entity_id = await _insert_entity(
        pg_session, user_id=committed_user.id, visibility="private"
    )

    await _set_promotion_guc(pg_session)
    await pg_session.execute(
        text("UPDATE ontology_entities SET visibility = 'public' WHERE id = :id"),
        {"id": entity_id},
    )
    await pg_session.flush()

    row = await pg_session.execute(
        text("SELECT visibility FROM ontology_entities WHERE id = :id"),
        {"id": entity_id},
    )
    assert row.scalar() == "public"


# ── One-directional ratchet ───────────────────────────────────────────────────


@pytest.mark.pg
async def test_demotion_rejected_even_with_guc(
    pg_session: AsyncSession, committed_user
) -> None:
    await _assert_promotion_guc_clear(pg_session)

    entity_id = await _insert_entity(
        pg_session, user_id=committed_user.id, visibility="private"
    )
    await _set_promotion_guc(pg_session)
    await pg_session.execute(
        text("UPDATE ontology_entities SET visibility = 'public' WHERE id = :id"),
        {"id": entity_id},
    )
    await pg_session.flush()

    with pytest.raises((StatementError, DBAPIError, ProgrammingError)) as exc_info:
        await pg_session.execute(
            text("UPDATE ontology_entities SET visibility = 'private' WHERE id = :id"),
            {"id": entity_id},
        )
        await pg_session.flush()

    err_msg = str(exc_info.value).lower()
    assert "demot" in err_msg or "ratchet" in err_msg or "downgrade" in err_msg


# ── BLOCKER 2 CHECK constraint guards ────────────────────────────────────────


@pytest.mark.pg
@pytest.mark.parametrize("bad_type", ["thread", "event", "email", "calendar"])
async def test_out_of_scope_entity_type_rejected(
    pg_session: AsyncSession, committed_user, bad_type: str
) -> None:
    with pytest.raises((StatementError, DBAPIError, ProgrammingError)):
        await pg_session.execute(
            text(
                "INSERT INTO ontology_entities "
                "(id, user_id, entity_type, external_key, visibility) "
                "VALUES (:id, :user_id, :entity_type, 'key-1', 'private')"
            ),
            {"id": uuid.uuid4(), "user_id": committed_user.id, "entity_type": bad_type},
        )
        await pg_session.flush()


@pytest.mark.pg
@pytest.mark.parametrize(
    "bad_rel", ["knows", "manages", "thread_received", "event_attended"]
)
async def test_out_of_scope_relationship_type_rejected(
    pg_session: AsyncSession, committed_user, bad_rel: str
) -> None:
    src_id = await _insert_entity(
        pg_session, user_id=committed_user.id, external_key=f"alice-{bad_rel}"
    )
    tgt_id = await _insert_entity(
        pg_session,
        user_id=committed_user.id,
        entity_type="project",
        external_key=f"proj-{bad_rel}",
    )

    with pytest.raises((StatementError, DBAPIError, ProgrammingError)):
        await pg_session.execute(
            text(
                "INSERT INTO ontology_relationships "
                "(id, user_id, source_entity_id, relationship_type, target_entity_id, visibility) "
                "VALUES (:id, :user_id, :src, :rel, :tgt, 'private')"
            ),
            {
                "id": uuid.uuid4(),
                "user_id": committed_user.id,
                "src": src_id,
                "rel": bad_rel,
                "tgt": tgt_id,
            },
        )
        await pg_session.flush()


# ── Composite FK tenant-integrity ─────────────────────────────────────────────


@pytest.mark.pg
async def test_tenant_integrity_fk_violation_rejected(
    pg_session: AsyncSession, committed_user
) -> None:
    from src.models.user import User

    other_user = User(
        id=uuid.uuid4(), email=f"other-{uuid.uuid4().hex[:8]}@example.com"
    )
    pg_session.add(other_user)
    await pg_session.flush()

    src_id = await _insert_entity(
        pg_session, user_id=committed_user.id, external_key="alice-x"
    )
    tgt_id = await _insert_entity(
        pg_session, user_id=other_user.id, entity_type="project", external_key="proj-y"
    )

    with pytest.raises((StatementError, DBAPIError, ProgrammingError)):
        await pg_session.execute(
            text(
                "INSERT INTO ontology_relationships "
                "(id, user_id, source_entity_id, relationship_type, target_entity_id, visibility) "
                "VALUES (:id, :user_id, :src, 'contributed_to', :tgt, 'private')"
            ),
            {
                "id": uuid.uuid4(),
                "user_id": other_user.id,
                "src": src_id,
                "tgt": tgt_id,
            },
        )
        await pg_session.flush()
