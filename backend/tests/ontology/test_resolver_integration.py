"""Integration tests — resolve.py against a real Postgres test DB.

Requires: pytest-asyncio, a reachable DATABASE_URL/DATABASE_URL_DIRECT
pointing at a test schema. Each test rolls back via a per-test
transaction fixture (see conftest.py).

Covers TC-037 through TC-043.

NOTE (fixed during FEAT-141 pr-test-analyzer pass): every call below
passes arguments in the resolver's REAL positional order,
``resolve(entities, db, user, domains=...)``. The previous draft of this
file called ``resolve(test_user, db_session, records, cfg)`` — user and
entities swapped, and the whole ``OntologyConfig`` object passed where
``domains: tuple[str, ...] | None`` belongs. That would have made every
test in this file raise inside ``resolve()``'s own ``_dedupe()`` (iterating
a ``User`` object) or ``_sweep_missing()`` (``set(cfg)`` on a non-iterable
dataclass) the moment a real DATABASE_URL made the suite actually run —
i.e. this entire integration surface (identity resolution, idempotent
upsert, cross-domain Person dedup, rename detection, per-user isolation)
had zero real coverage despite looking fully tested.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.ontology import OntologyEntityNote
from src.models.user import User
from src.services.ingestion.ontology.models import EntityRecord
from src.services.ingestion.ontology.resolve import resolve


@pytest_asyncio.fixture()
async def test_user(db_session: AsyncSession) -> User:
    user = User()
    user.id = uuid.uuid4()
    user.email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    user.hashed_password = "x"
    db_session.add(user)
    await db_session.flush()
    return user


def _entity_record(
    stable_entity_id: str = "event:test001",
    display_name: str = "Test Event",
    domain: str = "calendar",
    entity_type: str = "Event",
    source_updated_at: datetime | None = None,
) -> EntityRecord:
    return EntityRecord(
        entity_type=entity_type,
        stable_entity_id=stable_entity_id,
        display_name=display_name,
        domain=domain,
        source_id="test001",
        source_updated_at=source_updated_at or datetime.now(timezone.utc),
        relationships=[],
        raw_fields={},
    )


async def _fetch(db_session: AsyncSession, user_id, stable_entity_id: str):
    return (
        (
            await db_session.execute(
                select(OntologyEntityNote).where(
                    OntologyEntityNote.user_id == user_id,
                    OntologyEntityNote.stable_entity_id == stable_entity_id,
                )
            )
        )
        .scalars()
        .all()
    )


# ── TC-037 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_upserts_new_entity(db_session: AsyncSession, test_user: User):
    """resolve() creates a new OntologyEntityNote row for a brand-new entity."""
    records = [_entity_record()]
    result = await resolve(records, db_session, test_user, domains=("calendar",))

    rows = await _fetch(db_session, test_user.id, "event:test001")
    assert len(rows) == 1
    assert rows[0].display_name == "Test Event"
    assert "event:test001" in result.link_map


# ── TC-038 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_idempotent_no_duplicate(
    db_session: AsyncSession, test_user: User
):
    """Calling resolve() twice with same records must produce exactly one DB row."""
    records = [_entity_record()]
    await resolve(records, db_session, test_user, domains=("calendar",))
    await resolve(records, db_session, test_user, domains=("calendar",))

    rows = await _fetch(db_session, test_user.id, "event:test001")
    assert len(rows) == 1


# ── TC-039 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_cross_domain_person_dedup(
    db_session: AsyncSession, test_user: User
):
    """A Person appearing in both calendar and email extractors resolves to one row."""
    from src.services.ingestion.ontology.identity import person_id_from_email

    shared_id = person_id_from_email("shared@example.com")
    record_cal = EntityRecord(
        entity_type="Person",
        stable_entity_id=shared_id,
        display_name="Shared Person",
        domain="people",
        source_id="shared@example.com",
        source_updated_at=datetime.now(timezone.utc),
        relationships=[],
        raw_fields={"email": "shared@example.com"},
    )
    record_email = EntityRecord(
        entity_type="Person",
        stable_entity_id=shared_id,
        display_name="Shared Person",
        domain="people",
        source_id="shared@example.com",
        source_updated_at=datetime.now(timezone.utc) + timedelta(hours=1),
        relationships=[],
        raw_fields={"email": "shared@example.com"},
    )
    await resolve(
        [record_cal, record_email], db_session, test_user, domains=("calendar", "email")
    )

    rows = await _fetch(db_session, test_user.id, shared_id)
    assert len(rows) == 1


# ── TC-040 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_link_map_populated(db_session: AsyncSession, test_user: User):
    """result.link_map must contain every resolved entity."""
    records = [
        _entity_record(stable_entity_id="event:lm_test", display_name="Link Map Event")
    ]
    result = await resolve(records, db_session, test_user, domains=("calendar",))
    assert "event:lm_test" in result.link_map


# ── TC-041 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_unique_constraint_on_stable_entity_id(
    db_session: AsyncSession, test_user: User
):
    """Two different calls with same stable_entity_id do not violate uniqueness."""
    records = [_entity_record(stable_entity_id="event:uq001")]
    # First insert succeeds
    await resolve(records, db_session, test_user, domains=("calendar",))
    # Second upsert (same stable_entity_id) must not raise IntegrityError
    await resolve(records, db_session, test_user, domains=("calendar",))


# ── TC-042 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_rename_detected_when_display_name_changes(
    db_session: AsyncSession, test_user: User
):
    """When display_name changes for an existing entity, resolve emits rename_ops."""
    records_v1 = [
        _entity_record(stable_entity_id="event:rename_me", display_name="Old Name")
    ]
    await resolve(records_v1, db_session, test_user, domains=("calendar",))

    records_v2 = [
        _entity_record(stable_entity_id="event:rename_me", display_name="New Name")
    ]
    result_v2 = await resolve(records_v2, db_session, test_user, domains=("calendar",))
    assert len(result_v2.rename_ops) > 0


# ── TC-043 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_different_user_no_interference(
    db_session: AsyncSession, test_user: User
):
    """Entities for different users must not collide (user-scoped rows)."""
    user2 = User()
    user2.id = uuid.uuid4()
    user2.email = f"user2_{uuid.uuid4().hex[:8]}@example.com"
    user2.hashed_password = "x"
    db_session.add(user2)
    await db_session.flush()

    records = [_entity_record(stable_entity_id="event:shared_pool")]
    await resolve(records, db_session, test_user, domains=("calendar",))
    # Resolving same entity for user2 should create a separate row
    await resolve(records, db_session, user2, domains=("calendar",))

    all_rows = (
        (
            await db_session.execute(
                select(OntologyEntityNote).where(
                    OntologyEntityNote.stable_entity_id == "event:shared_pool"
                )
            )
        )
        .scalars()
        .all()
    )
    user_ids = {str(r.user_id) for r in all_rows}
    assert str(test_user.id) in user_ids
    assert str(user2.id) in user_ids


# ── TC-043b ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_sweeps_missing_entity_to_archived_after_threshold(
    db_session: AsyncSession, test_user: User
):
    """An entity tracked in a prior run but absent from 3 consecutive
    runs (within scope) is archived — the missed-runs sweep that keeps
    deleted-upstream entities from being tracked/rendered forever."""
    records = [_entity_record(stable_entity_id="event:will_vanish")]
    await resolve(records, db_session, test_user, domains=("calendar",))

    # Three runs in a row where the entity is no longer extracted.
    for _ in range(3):
        await resolve([], db_session, test_user, domains=("calendar",))

    rows = await _fetch(db_session, test_user.id, "event:will_vanish")
    assert len(rows) == 1
    assert rows[0].sync_state == "archived"
