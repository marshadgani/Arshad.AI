"""Extraction service integration tests.

All tests are @pytest.mark.pg (run against real Postgres) except
test_pg_session_requires_test_database_url, which must run even in a
PG_TESTS=skip environment since it's the guard against that environment
lying about coverage.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from src.services.ingestion import ontology_extract, runner

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _seed_activity(
    pg_session,
    user_id,
    count,
    *,
    base_time=None,
    login_prefix="alice",
    distinct_logins=False,
):
    """Seed `count` ingested_github_activity rows.

    By default every row has the same author ("alice"), one project. When
    ``distinct_logins`` is True, each row gets its own login
    (``{login_prefix}{i}``) against the same project, producing one entity
    upsert per row. ``provider_id`` is namespaced with a random prefix per
    call so multiple seed calls in one test don't collide on
    (user_id, kind, provider_id).
    """
    base_time = base_time or datetime.now(timezone.utc)
    prefix = uuid.uuid4().hex[:8]
    stmt = text(
        "INSERT INTO ingested_github_activity "
        "(id, user_id, occurred_at, kind, provider_id, raw, ingested_at) "
        "VALUES (:id, :user_id, :occurred_at, 'pr', :provider_id, "
        "CAST(:raw AS jsonb), now())"
    )
    params = [
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "occurred_at": base_time - timedelta(seconds=i),
            "provider_id": f"org/repo-{prefix}#{i}",
            "raw": json.dumps(
                {
                    "user": {
                        "login": f"{login_prefix}{i}" if distinct_logins else "alice"
                    }
                }
            ),
        }
        for i in range(count)
    ]
    # Single executemany round trip — a per-row await loop takes minutes
    # once count reaches thousands of rows.
    await pg_session.execute(stmt, params)


@pytest.mark.pg
@pytest.mark.asyncio
async def test_entity_derivation(committed_user, pg_session) -> None:
    await _seed_activity(pg_session, committed_user.id, 1)
    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )

    assert summary["entities_written"] == 2  # 1 person + 1 project
    persons = await pg_session.execute(
        text(
            "SELECT external_key FROM ontology_entities "
            "WHERE user_id = :uid AND entity_type = 'person'"
        ),
        {"uid": committed_user.id},
    )
    assert [row[0] for row in persons] == ["alice"]


@pytest.mark.pg
@pytest.mark.asyncio
async def test_relationship_derivation(committed_user, pg_session) -> None:
    await _seed_activity(pg_session, committed_user.id, 1)
    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )

    assert summary["relationships_written"] == 1
    rows = await pg_session.execute(
        text(
            "SELECT relationship_type FROM ontology_relationships WHERE user_id = :uid"
        ),
        {"uid": committed_user.id},
    )
    assert [row[0] for row in rows] == ["contributed_to"]


@pytest.mark.pg
@pytest.mark.asyncio
async def test_re_extraction_idempotency(committed_user, pg_session) -> None:
    await _seed_activity(pg_session, committed_user.id, 3)
    first = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )
    second = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )

    assert first["entities_written"] == second["entities_written"]
    entity_count = await pg_session.scalar(
        text("SELECT count(*) FROM ontology_entities WHERE user_id = :uid"),
        {"uid": committed_user.id},
    )
    assert entity_count == 2


@pytest.mark.pg
@pytest.mark.asyncio
async def test_visibility_preserved_on_reextract(committed_user, pg_session) -> None:
    await _seed_activity(pg_session, committed_user.id, 1)
    await ontology_extract.extract(user=committed_user, db=pg_session, payload={})

    entity_id = await pg_session.scalar(
        text(
            "SELECT id FROM ontology_entities WHERE user_id = :uid "
            "AND entity_type = 'person'"
        ),
        {"uid": committed_user.id},
    )
    await pg_session.execute(
        text("SELECT set_config('app.allow_visibility_promotion', 'true', true)")
    )
    await pg_session.execute(
        text("UPDATE ontology_entities SET visibility = 'public' WHERE id = :id"),
        {"id": entity_id},
    )
    await pg_session.execute(
        text("SELECT set_config('app.allow_visibility_promotion', 'false', true)")
    )

    await ontology_extract.extract(user=committed_user, db=pg_session, payload={})

    visibility = await pg_session.scalar(
        text("SELECT visibility FROM ontology_entities WHERE id = :id"),
        {"id": entity_id},
    )
    assert visibility == "public"


@pytest.mark.pg
@pytest.mark.asyncio
async def test_truncation_signal(committed_user, pg_session, caplog) -> None:
    await _seed_activity(pg_session, committed_user.id, 5001)
    with caplog.at_level(logging.WARNING):
        summary = await ontology_extract.extract(
            user=committed_user, db=pg_session, payload={}
        )

    assert summary["truncated"] is True
    assert summary["rows_scanned"] == 5000
    assert any("truncated" in rec.message.lower() for rec in caplog.records)


@pytest.mark.pg
@pytest.mark.asyncio
async def test_max_rows_above_5000_accepted_with_warning(
    committed_user, pg_session, caplog
) -> None:
    await _seed_activity(pg_session, committed_user.id, 1)
    with caplog.at_level(logging.WARNING):
        summary = await ontology_extract.extract(
            user=committed_user, db=pg_session, payload={"max_rows": 6000}
        )
    assert summary["truncated"] is False
    assert any("exceeds default cap" in rec.message for rec in caplog.records)


@pytest.mark.pg
@pytest.mark.asyncio
async def test_since_payload_filters_by_occurred_at(committed_user, pg_session) -> None:
    boundary = datetime.now(timezone.utc)
    await _seed_activity(
        pg_session, committed_user.id, 1, base_time=boundary - timedelta(days=2)
    )
    await _seed_activity(
        pg_session, committed_user.id, 1, base_time=boundary + timedelta(days=2)
    )

    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={"since": boundary.isoformat()}
    )
    assert summary["rows_scanned"] == 1


@pytest.mark.pg
@pytest.mark.asyncio
async def test_stale_classifications_counted(
    committed_user, pg_session, caplog
) -> None:
    await _seed_activity(pg_session, committed_user.id, 1)
    await ontology_extract.extract(user=committed_user, db=pg_session, payload={})

    entity_id = await pg_session.scalar(
        text(
            "SELECT id FROM ontology_entities WHERE user_id = :uid "
            "AND entity_type = 'person'"
        ),
        {"uid": committed_user.id},
    )
    await pg_session.execute(
        text("SELECT set_config('app.allow_visibility_promotion', 'true', true)")
    )
    await pg_session.execute(
        text(
            "UPDATE ontology_entities SET visibility = 'public', "
            "classification_checked_at = now() - interval '60 days' WHERE id = :id"
        ),
        {"id": entity_id},
    )
    await pg_session.execute(
        text("SELECT set_config('app.allow_visibility_promotion', 'false', true)")
    )

    with caplog.at_level(logging.WARNING):
        summary = await ontology_extract.extract(
            user=committed_user, db=pg_session, payload={}
        )
    assert summary["stale_classifications"] == 1
    assert any("stale classification" in rec.message.lower() for rec in caplog.records)


@pytest.mark.pg
@pytest.mark.asyncio
async def test_stale_classifications_excludes_private_fresh_and_counts_null(
    committed_user, pg_session
) -> None:
    """HIGH 2's query has three independent conditions
    (``visibility <> 'private'``, ``classification_checked_at IS NULL``,
    ``... < now() - interval '30 days'``); the happy-path test above only
    proves the "old public entity" arm. This proves the other two:
    a private entity (never classified) must NOT count regardless of
    staleness, a public entity checked 5 days ago must NOT count, and a
    public entity that was NEVER classified (classification_checked_at
    IS NULL) MUST count on its own, without ever having its timestamp
    set — the case the WARNING/index predicate exists for in the first
    place.
    """
    await pg_session.execute(
        text("SELECT set_config('app.allow_visibility_promotion', 'true', true)")
    )
    # public, never classified — must count (NULL arm)
    await pg_session.execute(
        text(
            "INSERT INTO ontology_entities "
            "(id, user_id, entity_type, external_key, visibility) "
            "VALUES (:id, :uid, 'person', 'never-classified', 'public')"
        ),
        {"id": uuid.uuid4(), "uid": committed_user.id},
    )
    # public, checked 5 days ago — must NOT count (fresh)
    fresh_id = uuid.uuid4()
    await pg_session.execute(
        text(
            "INSERT INTO ontology_entities "
            "(id, user_id, entity_type, external_key, visibility) "
            "VALUES (:id, :uid, 'person', 'fresh', 'public')"
        ),
        {"id": fresh_id, "uid": committed_user.id},
    )
    await pg_session.execute(
        text(
            "UPDATE ontology_entities SET classification_checked_at = "
            "now() - interval '5 days' WHERE id = :id"
        ),
        {"id": fresh_id},
    )
    # private, never classified — must NOT count (wrong visibility)
    await pg_session.execute(
        text(
            "INSERT INTO ontology_entities "
            "(id, user_id, entity_type, external_key, visibility) "
            "VALUES (:id, :uid, 'person', 'private-and-stale', 'private')"
        ),
        {"id": uuid.uuid4(), "uid": committed_user.id},
    )
    await pg_session.execute(
        text("SELECT set_config('app.allow_visibility_promotion', 'false', true)")
    )

    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )
    assert summary["stale_classifications"] == 1


@pytest.mark.pg
@pytest.mark.asyncio
async def test_max_rows_ceiling_clamped(committed_user, pg_session) -> None:
    """``_MAX_ROWS_CEILING = 50000`` — a payload requesting more must be
    clamped, not honored verbatim. Only reachable indirectly since the
    sweep would otherwise attempt LIMIT 50001+1; asserts extract() does
    not raise and rows_scanned never exceeds the ceiling."""
    await _seed_activity(pg_session, committed_user.id, 1)
    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={"max_rows": 999_999}
    )
    assert summary["rows_scanned"] <= 50_000


@pytest.mark.pg
@pytest.mark.asyncio
async def test_invalid_max_rows_falls_back_to_default_with_warning(
    committed_user, pg_session, caplog
) -> None:
    """``_clamp_max_rows`` treats a non-coercible ``max_rows`` (e.g. a
    string) as caller error and logs a WARNING rather than silently
    using the default — this path had zero coverage."""
    await _seed_activity(pg_session, committed_user.id, 1)
    with caplog.at_level(logging.WARNING):
        summary = await ontology_extract.extract(
            user=committed_user, db=pg_session, payload={"max_rows": "not-a-number"}
        )
    assert summary["rows_scanned"] == 1
    assert any("invalid max_rows" in rec.message.lower() for rec in caplog.records)


def test_naive_since_rejected() -> None:
    """A tz-naive `since` is reinterpreted by Postgres in the session
    TimeZone, silently shifting the sweep window. It must be rejected, not
    guessed at. Pure — no DB needed, so it runs in every CI configuration."""
    with pytest.raises(ontology_extract.IngestionError) as exc_info:
        ontology_extract.ExtractOptions.from_payload(
            {"since": "2026-09-01T00:00:00"}
        )
    assert "timezone" in str(exc_info.value)


def test_aware_since_accepted() -> None:
    options = ontology_extract.ExtractOptions.from_payload(
        {"since": "2026-09-01T00:00:00+00:00"}
    )
    assert options.since is not None and options.since.tzinfo is not None


@pytest.mark.pg
@pytest.mark.asyncio
async def test_invalid_since_raises_ingestion_error(committed_user, pg_session) -> None:
    """``_parse_since`` raises ``IngestionError`` for a non-ISO ``since``
    value — the explicit validation branch had no test exercising it."""
    from src.services.ingestion.errors import IngestionError

    with pytest.raises(IngestionError):
        await ontology_extract.extract(
            user=committed_user,
            db=pg_session,
            payload={"since": "not-a-date"},
        )


@pytest.mark.pg
@pytest.mark.asyncio
async def test_extract_on_empty_activity_is_a_noop(committed_user, pg_session) -> None:
    """No ingested_github_activity rows for this user: extract() must not
    raise, and must report zeros rather than crash on an empty sweep."""
    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )
    assert summary["entities_written"] == 0
    assert summary["relationships_written"] == 0
    assert summary["rows_scanned"] == 0
    assert summary["truncated"] is False


@pytest.mark.pg
@pytest.mark.asyncio
async def test_re_extraction_idempotency_relationships(
    committed_user, pg_session
) -> None:
    """Companion to test_re_extraction_idempotency: that test only checks
    entity count stability across two extract() runs. The relationship
    upsert uses ON CONFLICT DO NOTHING on a different unique constraint —
    it needs its own regression so a change that breaks relationship
    idempotency (but not entity idempotency) isn't invisible."""
    await _seed_activity(pg_session, committed_user.id, 3)
    await ontology_extract.extract(user=committed_user, db=pg_session, payload={})
    first_count = await pg_session.scalar(
        text("SELECT count(*) FROM ontology_relationships WHERE user_id = :uid"),
        {"uid": committed_user.id},
    )

    await ontology_extract.extract(user=committed_user, db=pg_session, payload={})
    second_count = await pg_session.scalar(
        text("SELECT count(*) FROM ontology_relationships WHERE user_id = :uid"),
        {"uid": committed_user.id},
    )

    assert first_count == second_count == 1


@pytest.mark.pg
@pytest.mark.asyncio
async def test_extract_does_not_touch_other_users_entities(
    committed_user, pg_session
) -> None:
    """Tenant isolation at the extract() call boundary itself (not just
    the relationship FK, which is covered in test_ontology_security.py):
    running extract() for one user must not read or write another
    user's rows, even when both have activity seeded."""
    other_user_id = uuid.uuid4()
    await pg_session.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email)"),
        {"id": other_user_id, "email": f"other-{other_user_id}@example.com"},
    )
    await _seed_activity(pg_session, other_user_id, 1, login_prefix="other-user-login")

    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )

    assert summary["entities_written"] == 0
    leaked = await pg_session.scalar(
        text(
            "SELECT count(*) FROM ontology_entities WHERE user_id = :uid "
            "AND external_key LIKE 'other-user-login%'"
        ),
        {"uid": committed_user.id},
    )
    assert leaked == 0


@pytest.mark.pg
@pytest.mark.asyncio
async def test_runner_dispatches_ontology_extractor(committed_user, pg_session) -> None:
    await _seed_activity(pg_session, committed_user.id, 1)
    summary = await runner.run(
        dag_id="ontology_extractor",
        user_id=committed_user.id,
        payload={},
        db=pg_session,
    )
    assert "entities_written" in summary


@pytest.mark.pg
@pytest.mark.asyncio
async def test_cli_script_inserts_queue_row(pg_session) -> None:
    """Deliberately does NOT use the shared ``committed_user`` fixture: the
    CLI script runs as a genuinely separate subprocess with its own DB
    connection, which cannot see a user that only lives inside
    ``pg_session``'s SAVEPOINT tree — inserting a dag_trigger_queue row
    referencing it would hit a real FK violation. Seeds and cleans up its
    own truly-committed user instead, same reasoning as
    ``test_extraction_survives_worker_session_close``."""
    import os
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.models.user import User
    from tests.conftest import _require_test_database_url

    engine = create_async_engine(
        _require_test_database_url(),
        connect_args={"statement_cache_size": 0},
        poolclass=NullPool,
    )
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    try:
        async with sessionmaker() as seed_db:
            seed_db.add(
                User(
                    id=user_id,
                    email=f"test-{user_id.hex[:8]}@example.com",
                    name="Test User",
                )
            )
            await seed_db.commit()

        env = {**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"]}
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "ontology_extract.py"),
                "--user-id",
                str(user_id),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        row = await pg_session.execute(
            text(
                "SELECT dag_id FROM dag_trigger_queue "
                "WHERE user_id = :uid ORDER BY requested_at DESC LIMIT 1"
            ),
            {"uid": user_id},
        )
        assert row.scalar_one() == "ontology_extractor"
    finally:
        async with sessionmaker() as cleanup_db:
            await cleanup_db.execute(
                text("DELETE FROM users WHERE id = :uid"), {"uid": user_id}
            )
            await cleanup_db.commit()
        await engine.dispose()


@pytest.mark.pg
@pytest.mark.asyncio
async def test_large_entity_set_writes_every_row(committed_user, pg_session) -> None:
    # 600 distinct logins against one project — asserts the entity-upsert
    # loop writes the whole set and never silently drops the tail.
    await _seed_activity(
        pg_session, committed_user.id, 600, login_prefix="dev", distinct_logins=True
    )
    summary = await ontology_extract.extract(
        user=committed_user, db=pg_session, payload={}
    )
    assert summary["entities_written"] == 601  # 600 persons + 1 project


@pytest.mark.pg
@pytest.mark.asyncio
async def test_extraction_survives_worker_session_close() -> None:
    """Regression: the production commit boundary.

    Every other test in this module hands ``extract()`` the pg_session
    fixture and asserts inside that same open transaction — so they pass
    whether or not anything is ever committed. Production does not work
    that way: ``queue_worker._process`` (and the Airflow helper
    ``run_ingest_for_row``) wrap the runner in
    ``async with AsyncSessionLocal() as db:`` and never commit, so
    ``AsyncSession.__aexit__`` rolls back anything left open.

    This test reproduces that exact shape — run the runner in a session
    that is closed without an external commit, then assert the rows are
    still there when read back on a *different* connection. Before the
    fix it reported entities_written=2 / relationships_written=1 and
    persisted zero rows.

    Deliberately does NOT use the shared ``committed_user`` fixture: that
    user only lives inside the SAVEPOINT tree ``pg_session``/``pg_connection``
    share, invisible to the genuinely separate connections this test opens
    (via a fresh engine, matching production's ``AsyncSessionLocal``) — a
    separate connection querying it hits a real FK violation, not a
    visibility quirk. This test seeds and cleans up its own truly-committed
    user instead.
    """
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.models.user import User
    from tests.conftest import _require_test_database_url

    engine = create_async_engine(
        _require_test_database_url(),
        connect_args={"statement_cache_size": 0},
        poolclass=NullPool,
    )
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    try:
        async with sessionmaker() as seed_db:
            seed_db.add(
                User(
                    id=user_id,
                    email=f"test-{user_id.hex[:8]}@example.com",
                    name="Test User",
                )
            )
            # Explicit flush before the raw text() INSERT below — that
            # statement isn't a Core construct autoflush is guaranteed to
            # precede, and the FK to users must already be satisfiable.
            await seed_db.flush()
            await _seed_activity(seed_db, user_id, 1)
            await seed_db.commit()

        # Exactly what queue_worker._process does: no commit by the caller.
        async with sessionmaker() as runner_db:
            summary = await runner.run(
                dag_id="ontology_extractor",
                user_id=user_id,
                payload={},
                db=runner_db,
            )
        assert summary["entities_written"] == 2
        assert summary["relationships_written"] == 1

        async with sessionmaker() as verify_db:
            entities = await verify_db.scalar(
                text("SELECT count(*) FROM ontology_entities WHERE user_id = :uid"),
                {"uid": user_id},
            )
            relationships = await verify_db.scalar(
                text(
                    "SELECT count(*) FROM ontology_relationships WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        assert entities == 2, (
            "extract() did not commit — the runner reported success but the "
            "rows were rolled back when the worker's session closed."
        )
        assert relationships == 1, (
            "Relationship rows were rolled back on worker session close."
        )
    finally:
        # This user and its rows were genuinely committed on a separate
        # connection, outside pg_session's SAVEPOINT tree — nothing else
        # rolls them back. Delete explicitly; ON DELETE CASCADE removes the
        # ingested activity, entities, and relationships with it.
        async with sessionmaker() as cleanup_db:
            await cleanup_db.execute(
                text("DELETE FROM users WHERE id = :uid"), {"uid": user_id}
            )
            await cleanup_db.commit()
        await engine.dispose()


def test_pg_session_requires_test_database_url(monkeypatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    from tests.conftest import _require_test_database_url

    with pytest.raises(RuntimeError) as exc_info:
        _require_test_database_url()
    assert "TEST_DATABASE_URL" in str(exc_info.value)
