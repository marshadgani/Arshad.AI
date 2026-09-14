"""Integration tests for src/skills/service.py and src/skills/repository.py.

Requires a live Postgres. Every test carries `@pytest.mark.requires_db`,
which backend/conftest.py auto-skips unless `RUN_DB_TESTS` is set.
`DATABASE_URL` is deliberately NOT the gate: conftest.py installs a
placeholder DSN with `os.environ.setdefault`, so a DATABASE_URL-based guard
never fires and these tests would try to dial localhost:5432 on every
machine without Postgres.

Isolation: each test runs inside an outer transaction that is rolled back
in teardown, with the session joined to it via
`join_transaction_mode="create_savepoint"` so that the `db.commit()` calls
inside `service.register_skill` release a SAVEPOINT rather than committing
for real. The fixture also empties `skill_registry` *inside* that
transaction, so assertions on absolute row counts (the mass-delete guard in
particular) are deterministic regardless of how many real skills the target
database happens to hold. The truncate is rolled back with everything else.

REQ links: FR-1, FR-3, NFR-1, NFR-5, SC-2, SC-4, SC-6.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytestmark = pytest.mark.requires_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def engine():
    """Function-scoped deliberately.

    pytest-asyncio gives each test its own event loop by default. An engine
    (and therefore an asyncpg connection) created in a module- or
    session-scoped async fixture is bound to the loop that created it, and
    reusing it from a later test's loop fails with
    `InterfaceError: cannot perform operation: another operation is in
    progress`. A fresh engine per test costs one connection setup and keeps
    the suite deterministic.
    """
    e = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    try:
        yield e
    finally:
        await e.dispose()


@pytest_asyncio.fixture()
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Session joined to an outer transaction that is always rolled back.

    `join_transaction_mode="create_savepoint"` is what makes this safe for
    code under test that commits: the commit releases a SAVEPOINT and the
    outer transaction stays open until this fixture rolls it back.
    """
    from src.models.skill import SkillRegistry

    async with engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        session = session_factory()
        # Start from a known-empty table *within* this transaction so tests
        # can assert on absolute counts. Rolled back with everything else.
        await session.execute(delete(SkillRegistry))
        await session.flush()
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


def _skill_row(**overrides) -> dict:
    base = {
        "skill_name": f"test__{uuid.uuid4().hex[:8]}",
        "display_name": "Test Skill",
        "description": "A test skill for integration purposes.",
        "source_repo": "test-repo",
        "category": "other",
    }
    return base | overrides


def _manifest_path(tmp_path: Path, rows: list) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(rows) + "\n", encoding="utf-8")
    return p


async def _count_named(db: AsyncSession, skill_name: str) -> int:
    from src.models.skill import SkillRegistry

    return (
        await db.scalar(
            select(func.count())
            .select_from(SkillRegistry)
            .where(SkillRegistry.skill_name == skill_name)
        )
        or 0
    )


# ---------------------------------------------------------------------------
# register_skill — FR-3
# ---------------------------------------------------------------------------


class TestRegisterSkill:
    @pytest.mark.asyncio
    async def test_first_registration_returns_registered(self, db):
        """TC-053: New skill → action='registered'."""
        from src.schemas.ai_ecosystem import RegisterSkillRequest
        from src.skills.service import register_skill

        action = await register_skill(db, RegisterSkillRequest(**_skill_row()))
        assert action == "registered"

    @pytest.mark.asyncio
    async def test_second_registration_returns_updated(self, db):
        """TC-054: Same skill_name registered again → action='updated'."""
        from src.schemas.ai_ecosystem import RegisterSkillRequest
        from src.skills.service import register_skill

        req = RegisterSkillRequest(**_skill_row())
        await register_skill(db, req)
        assert await register_skill(db, req) == "updated"

    @pytest.mark.asyncio
    async def test_re_registration_does_not_duplicate_the_row(self, db):
        """Idempotency at the row level, not just the returned action."""
        from src.schemas.ai_ecosystem import RegisterSkillRequest
        from src.skills.service import register_skill

        row = _skill_row()
        await register_skill(db, RegisterSkillRequest(**row))
        await register_skill(db, RegisterSkillRequest(**row))
        assert await _count_named(db, row["skill_name"]) == 1

    @pytest.mark.asyncio
    async def test_update_changes_display_name(self, db):
        """TC-055: Re-registration with a new display_name persists the change."""
        from src.schemas.ai_ecosystem import RegisterSkillRequest
        from src.skills import repository
        from src.skills.service import register_skill

        row = _skill_row(display_name="Original Name")
        await register_skill(db, RegisterSkillRequest(**row))
        row["display_name"] = "Updated Name"
        await register_skill(db, RegisterSkillRequest(**row))

        stored = await repository.get_by_name(db, row["skill_name"])
        assert stored is not None
        assert stored.display_name == "Updated Name"

    @pytest.mark.asyncio
    async def test_id_and_created_at_unchanged_on_update(self, db):
        """TC-056: id and created_at are write-once, not overwritten on re-register."""
        from src.schemas.ai_ecosystem import RegisterSkillRequest
        from src.skills import repository
        from src.skills.service import register_skill

        row = _skill_row()
        await register_skill(db, RegisterSkillRequest(**row))
        first = await repository.get_by_name(db, row["skill_name"])
        assert first is not None
        first_id, first_created_at = first.id, first.created_at

        await register_skill(db, RegisterSkillRequest(**row))
        second = await repository.get_by_name(db, row["skill_name"])
        assert second is not None
        assert second.id == first_id
        assert second.created_at == first_created_at


# ---------------------------------------------------------------------------
# sync_from_manifest — FR-1, FR-3, NFR-1, NFR-5
# ---------------------------------------------------------------------------


class TestSyncFromManifest:
    @pytest.mark.asyncio
    async def test_first_run_inserts_rows(self, db, tmp_path, monkeypatch):
        """TC-057: sync_from_manifest() inserts every row from the manifest."""
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        rows = [_skill_row(skill_name=f"test__skill{i}") for i in range(5)]
        monkeypatch.setattr(
            manifest_mod, "MANIFEST_PATH", _manifest_path(tmp_path, rows)
        )
        stats = await sync_from_manifest(db)
        assert stats["registered"] == 5
        assert await repository.count(db) == 5

    @pytest.mark.asyncio
    async def test_second_run_is_idempotent_row_count(self, db, tmp_path, monkeypatch):
        """TC-058: Running sync twice produces an identical row count (FR-3)."""
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        rows = [_skill_row(skill_name=f"test__idem{i}") for i in range(3)]
        monkeypatch.setattr(
            manifest_mod, "MANIFEST_PATH", _manifest_path(tmp_path, rows)
        )
        await sync_from_manifest(db)
        first = await repository.count(db)
        await sync_from_manifest(db)
        assert await repository.count(db) == first == 3

    @pytest.mark.asyncio
    async def test_updated_row_propagated_on_second_run(
        self, db, tmp_path, monkeypatch
    ):
        """TC-059: A changed manifest row updates the stored display_name."""
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        skill_name = f"test__update{uuid.uuid4().hex[:6]}"
        rows = [_skill_row(skill_name=skill_name, display_name="Before")]
        mp = _manifest_path(tmp_path, rows)
        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", mp)
        await sync_from_manifest(db)

        rows[0]["display_name"] = "After"
        mp.write_text(json.dumps(rows) + "\n", encoding="utf-8")
        await sync_from_manifest(db)

        stored = await repository.get_by_name(db, skill_name)
        assert stored is not None
        assert stored.display_name == "After"

    @pytest.mark.asyncio
    async def test_removed_row_is_deleted_on_next_sync(self, db, tmp_path, monkeypatch):
        """Convergence: a skill dropped from the manifest leaves the registry,
        provided the mass-delete guard does not trip."""
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        rows = [_skill_row(skill_name=f"test__conv{i}") for i in range(4)]
        mp = _manifest_path(tmp_path, rows)
        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", mp)
        await sync_from_manifest(db)

        # Drop one of four — 3 >= 4 * 0.5, so the guard stays out of the way.
        mp.write_text(json.dumps(rows[:3]) + "\n", encoding="utf-8")
        stats = await sync_from_manifest(db)

        assert stats["deleted"] == 1
        assert await repository.get_by_name(db, "test__conv3") is None
        assert await repository.count(db) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_stats_when_manifest_missing(
        self, db, tmp_path, monkeypatch
    ):
        """TC-060: Missing manifest → {registered: 0, deleted: 0}, no exception.

        Nothing is deleted either: a missing artifact must never be read as
        "the disk has no skills".
        """
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        await repository.bulk_upsert(db, [_skill_row()])
        await db.flush()

        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", tmp_path / "missing.json")
        stats = await sync_from_manifest(db)
        assert stats == {"registered": 0, "deleted": 0}
        assert await repository.count(db) == 1

    @pytest.mark.asyncio
    async def test_never_raises_on_malformed_manifest(self, db, tmp_path, monkeypatch):
        """TC-061: Malformed JSON → empty stats, never raises (NFR-1)."""
        import src.skills.manifest as manifest_mod
        from src.skills.service import sync_from_manifest

        bad = tmp_path / "manifest.json"
        bad.write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", bad)
        try:
            stats = await sync_from_manifest(db)
        except Exception as exc:  # pragma: no cover - the assertion is the point
            pytest.fail(f"sync_from_manifest raised unexpectedly: {exc}")
        assert stats == {"registered": 0, "deleted": 0}

    @pytest.mark.asyncio
    async def test_never_raises_when_a_row_violates_the_schema(
        self, db, tmp_path, monkeypatch
    ):
        """A manifest row with an illegal category violates the CHECK
        constraint mid-sync. The function must swallow it, roll back its own
        partial writes and leave the session usable — otherwise container
        startup dies on a bad build artifact (NFR-1)."""
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        monkeypatch.setattr(
            manifest_mod,
            "MANIFEST_PATH",
            _manifest_path(tmp_path, [_skill_row(category="not-a-category")]),
        )
        stats = await sync_from_manifest(db)
        assert stats == {"registered": 0, "deleted": 0}
        # Session must still be usable after the internal rollback.
        assert await repository.count(db) >= 0

    @pytest.mark.asyncio
    async def test_mass_delete_guard_skips_deletion(self, db, tmp_path, monkeypatch):
        """TC-062: A manifest covering <50% of existing rows skips deletions."""
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        all_rows = [_skill_row(skill_name=f"test__guard{i}") for i in range(10)]
        monkeypatch.setattr(
            manifest_mod, "MANIFEST_PATH", _manifest_path(tmp_path, all_rows)
        )
        await sync_from_manifest(db)
        assert await repository.count(db) == 10

        # Only 2 of 10 — below MASS_DELETE_GUARD_RATIO, so nothing is removed.
        monkeypatch.setattr(
            manifest_mod, "MANIFEST_PATH", _manifest_path(tmp_path, all_rows[:2])
        )
        stats = await sync_from_manifest(db)
        assert stats["deleted"] == 0
        assert await repository.count(db) == 10

    @pytest.mark.asyncio
    async def test_500_row_manifest_chunks_correctly(self, db, tmp_path, monkeypatch):
        """TC-063: 501 rows upsert across multiple chunks without losing any (NFR-5)."""
        import src.skills.manifest as manifest_mod
        from src.skills import repository
        from src.skills.service import sync_from_manifest

        large_rows = [_skill_row(skill_name=f"test__chunk{i:04d}") for i in range(501)]
        monkeypatch.setattr(
            manifest_mod, "MANIFEST_PATH", _manifest_path(tmp_path, large_rows)
        )
        stats = await sync_from_manifest(db)
        assert stats["registered"] == 501
        assert await repository.count(db) == 501


# ---------------------------------------------------------------------------
# bulk_upsert — repository layer
# ---------------------------------------------------------------------------


class TestBulkUpsert:
    @pytest.mark.asyncio
    async def test_on_conflict_updates_mutable_columns(self, db):
        """TC-064: ON CONFLICT refreshes display_name/description/source_repo/category."""
        from src.skills import repository

        skill_name = f"test__conflict{uuid.uuid4().hex[:6]}"
        await repository.bulk_upsert(
            db,
            [
                dict(
                    skill_name=skill_name,
                    display_name="First",
                    description="D.",
                    source_repo="r",
                    category="other",
                )
            ],
        )
        await repository.bulk_upsert(
            db,
            [
                dict(
                    skill_name=skill_name,
                    display_name="Second",
                    description="D2.",
                    source_repo="r2",
                    category="development",
                )
            ],
        )
        await db.flush()

        stored = await repository.get_by_name(db, skill_name)
        assert stored is not None
        assert stored.display_name == "Second"
        assert stored.description == "D2."
        assert stored.source_repo == "r2"
        assert stored.category == "development"

    @pytest.mark.asyncio
    async def test_no_duplicate_rows_on_conflict(self, db):
        """TC-065: Upsert the same skill twice; the row count stays 1 (FR-3)."""
        from src.skills import repository

        skill_name = f"test__nodup{uuid.uuid4().hex[:6]}"
        row = dict(
            skill_name=skill_name,
            display_name="X",
            description="D.",
            source_repo="r",
            category="other",
        )
        await repository.bulk_upsert(db, [row])
        await repository.bulk_upsert(db, [row])
        await db.flush()
        assert await _count_named(db, skill_name) == 1

    @pytest.mark.asyncio
    async def test_empty_row_list_is_a_no_op(self, db):
        """Zero rows must not emit an INSERT with no VALUES (a syntax error)."""
        from src.skills import repository

        await repository.bulk_upsert(db, [])
        assert await repository.count(db) == 0

    @pytest.mark.asyncio
    async def test_chunking_spans_more_than_one_statement(self, db):
        """Exactly CHUNK_SIZE + 1 rows exercises the loop boundary."""
        from src.skills import repository

        rows = [
            dict(
                skill_name=f"test__edge{i:04d}",
                display_name="E",
                description="D.",
                source_repo="r",
                category="other",
            )
            for i in range(repository.CHUNK_SIZE + 1)
        ]
        await repository.bulk_upsert(db, rows)
        await db.flush()
        assert await repository.count(db) == repository.CHUNK_SIZE + 1


# ---------------------------------------------------------------------------
# delete_missing — repository layer
# ---------------------------------------------------------------------------


class TestDeleteMissing:
    @pytest.mark.asyncio
    async def test_deletes_skills_not_in_keep_set(self, db):
        """TC-066: Skills absent from keep_names are deleted; kept ones survive."""
        from src.skills import repository

        keep = f"test__keep{uuid.uuid4().hex[:6]}"
        remove = f"test__remove{uuid.uuid4().hex[:6]}"
        await repository.bulk_upsert(
            db,
            [
                dict(
                    skill_name=keep,
                    display_name="K",
                    description="D.",
                    source_repo="r",
                    category="other",
                ),
                dict(
                    skill_name=remove,
                    display_name="R",
                    description="D.",
                    source_repo="r",
                    category="other",
                ),
            ],
        )
        await db.flush()

        assert await repository.delete_missing(db, {keep}) == 1
        assert await repository.get_by_name(db, remove) is None
        assert await repository.get_by_name(db, keep) is not None

    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self, db):
        """TC-067: The return value equals the number of rows actually deleted."""
        from src.skills import repository

        names = [f"test__del{uuid.uuid4().hex[:6]}" for _ in range(3)]
        await repository.bulk_upsert(
            db,
            [
                dict(
                    skill_name=n,
                    display_name="D",
                    description="D.",
                    source_repo="r",
                    category="other",
                )
                for n in names
            ],
        )
        await db.flush()
        assert await repository.delete_missing(db, set()) == 3
        assert await repository.count(db) == 0


# ---------------------------------------------------------------------------
# list_page — repository layer filters used by GET /skills
# ---------------------------------------------------------------------------


class TestListPage:
    @pytest_asyncio.fixture()
    async def seeded(self, db):
        from src.skills import repository

        rows = [
            dict(
                skill_name="lp__alpha",
                display_name="Alpha",
                description="D.",
                source_repo="r",
                category="development",
            ),
            dict(
                skill_name="lp__beta",
                display_name="Beta 100%",
                description="D.",
                source_repo="r",
                category="security",
            ),
            dict(
                skill_name="lp__gamma",
                display_name="Gamma",
                description="D.",
                source_repo="r",
                category="security",
            ),
        ]
        await repository.bulk_upsert(db, rows)
        await db.flush()
        return db

    @pytest.mark.asyncio
    async def test_total_is_unfiltered_by_limit(self, seeded):
        from src.skills import repository

        rows, total = await repository.list_page(seeded, limit=1, offset=0)
        assert len(rows) == 1
        assert total == 3

    @pytest.mark.asyncio
    async def test_category_filter(self, seeded):
        from src.skills import repository

        rows, total = await repository.list_page(
            seeded, limit=50, offset=0, category="security"
        )
        assert total == 2
        assert {r.skill_name for r in rows} == {"lp__beta", "lp__gamma"}

    @pytest.mark.asyncio
    async def test_ordering_is_category_then_display_name(self, seeded):
        from src.skills import repository

        rows, _ = await repository.list_page(seeded, limit=50, offset=0)
        keys = [(r.category, r.display_name, r.skill_name) for r in rows]
        assert keys == sorted(keys)

    @pytest.mark.asyncio
    async def test_percent_in_q_is_escaped_not_a_wildcard(self, seeded):
        """A bare '%' must match the literal character, not every row."""
        from src.skills import repository

        rows, total = await repository.list_page(seeded, limit=50, offset=0, q="100%")
        assert total == 1
        assert rows[0].skill_name == "lp__beta"

    @pytest.mark.asyncio
    async def test_underscore_in_q_is_escaped_not_a_wildcard(self, seeded):
        """'p__a' matches lp__alpha literally; it must not behave as 'p??a'."""
        from src.skills import repository

        _, total = await repository.list_page(seeded, limit=50, offset=0, q="p__a")
        assert total == 1

    @pytest.mark.asyncio
    async def test_q_is_case_insensitive(self, seeded):
        from src.skills import repository

        _, total = await repository.list_page(seeded, limit=50, offset=0, q="ALPHA")
        assert total == 1
