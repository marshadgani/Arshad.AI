"""Integration tests — OntologyEntityNote model constraints and indexes.

Verifies:
- UNIQUE(user_id, stable_entity_id) blocks duplicates
- UNIQUE(user_id, vault_path) blocks path collision
- Default values apply on insert
- CASCADE delete works
- Indexes exist post-migration

Covers TC-044 through TC-049.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.ontology import OntologyEntityNote
from src.models.user import User


@pytest_asyncio.fixture()
async def plain_user(db_session: AsyncSession) -> User:
    user = User()
    user.id = uuid.uuid4()
    user.email = f"constraint_test_{uuid.uuid4().hex[:8]}@example.com"
    user.hashed_password = "x"
    db_session.add(user)
    await db_session.flush()
    return user


def _minimal_row(
    user_id: uuid.UUID, stable_entity_id: str, vault_path: str
) -> OntologyEntityNote:
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = user_id
    row.domain = "calendar"
    row.entity_type = "Event"
    row.stable_entity_id = stable_entity_id
    row.display_name = "Test Entity"
    row.vault_path = vault_path
    return row


# ── TC-044 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unique_stable_entity_id_per_user(
    db_session: AsyncSession, plain_user: User
):
    """UNIQUE(user_id, stable_entity_id) blocks a second row with same IDs."""
    row1 = _minimal_row(
        plain_user.id, "event:dup_entity", "entities/calendar/Event/event:dup_entity.md"
    )
    row2 = _minimal_row(
        plain_user.id,
        "event:dup_entity",
        "entities/calendar/Event/event:dup_entity_2.md",
    )
    db_session.add(row1)
    await db_session.flush()
    db_session.add(row2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── TC-045 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unique_vault_path_per_user(db_session: AsyncSession, plain_user: User):
    """UNIQUE(user_id, vault_path) blocks two different entities at same path."""
    shared_path = "entities/calendar/Event/shared.md"
    row1 = _minimal_row(plain_user.id, "event:entity_a", shared_path)
    row2 = _minimal_row(plain_user.id, "event:entity_b", shared_path)
    db_session.add(row1)
    await db_session.flush()
    db_session.add(row2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── TC-046 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_default_values_on_insert(db_session: AsyncSession, plain_user: User):
    """Defaults: blob_sha='', frontmatter_json={}, tags=[], relationships=[], sync_state='pending'."""
    row = _minimal_row(
        plain_user.id, "event:defaults_test", "entities/calendar/Event/defaults.md"
    )
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)

    assert row.blob_sha == ""
    assert row.frontmatter_json == {}
    assert row.tags == []
    assert row.relationships == []
    assert row.sync_state == "pending"


# ── TC-047 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_created_at_updated_at_auto_populate(
    db_session: AsyncSession, plain_user: User
):
    row = _minimal_row(
        plain_user.id, "event:ts_test", "entities/calendar/Event/ts_test.md"
    )
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)
    assert row.created_at is not None
    assert row.updated_at is not None


# ── TC-048 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cascade_delete_on_user_removal(
    db_session: AsyncSession, plain_user: User
):
    """Deleting a user must cascade-delete their ontology_entity_notes rows."""
    row = _minimal_row(
        plain_user.id, "event:cascade_test", "entities/calendar/Event/cascade.md"
    )
    db_session.add(row)
    await db_session.flush()

    await db_session.delete(plain_user)
    await db_session.flush()

    orphans = (
        (
            await db_session.execute(
                select(OntologyEntityNote).where(
                    OntologyEntityNote.user_id == plain_user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(orphans) == 0


# ── TC-049 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_required_indexes_exist(db_session: AsyncSession):
    """Verify that the expected composite indexes exist in the DB (post-migration smoke test)."""
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'ontology_entity_notes' "
            "AND indexname IN ("
            "  'ix_ontology_user_domain_type', "
            "  'ix_ontology_user_sync_state', "
            "  'ix_ontology_user_seen'"
            ")"
        )
    )
    found = {row[0] for row in result.fetchall()}
    assert "ix_ontology_user_domain_type" in found
    assert "ix_ontology_user_sync_state" in found
    assert "ix_ontology_user_seen" in found
