"""Unit tests for FEAT-167 — ontology_visibility service layer.

A routing fake session stands in for AsyncSession so no Postgres is needed;
real trigger/tenant behaviour lives in test_ontology_visibility_pg.py.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.services.ingestion import ontology_visibility as svc
from src.services.ingestion.ontology_visibility import (
    MAX_BULK_IDS,
    EntityNotFoundError,
    set_entity_visibility,
)


class FakeSession:
    """Routes each statement by its SQL text and records (kind, params)."""

    def __init__(self, owned: set[uuid.UUID], changed: set[uuid.UUID] | None = None):
        self._owned = owned
        self._changed = owned if changed is None else changed
        self.calls: list[tuple[str, dict]] = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        result = MagicMock()
        if "FOR UPDATE" in sql:
            kind = "lock"
            ids = set(params["ids"])
            result.fetchall.return_value = [(i,) for i in ids if i in self._owned]
        elif "set_config" in sql:
            kind = "guc"
        elif sql.startswith("UPDATE ontology_entities"):
            kind = "entities"
            result.fetchall.return_value = [
                (i,) for i in params["ids"] if i in self._changed
            ]
        elif "SET visibility = 'public'" in sql:
            kind = "rel_promote"
            result.rowcount = 0
        elif "SET visibility = 'private'" in sql:
            kind = "rel_demote"
            result.rowcount = 0
        else:  # pragma: no cover - guards against new unrouted statements
            raise AssertionError(f"unrouted statement: {sql}")
        self.calls.append((kind, params))
        return result

    @property
    def kinds(self) -> list[str]:
        return [k for k, _ in self.calls]


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


@pytest.mark.asyncio
async def test_promotion_orders_lock_guc_entities_then_relationships():
    uid, eid = uuid.uuid4(), uuid.uuid4()
    s = FakeSession({eid})
    result = await set_entity_visibility(s, uid, [eid], "public")
    assert s.kinds == ["lock", "guc", "entities", "rel_promote"]
    assert result == {"updated": 1, "unchanged": 0}


@pytest.mark.asyncio
async def test_guc_is_transaction_local_and_never_session_level():
    sql = str(svc._SET_PROMOTION_GUC)
    assert "app.allow_visibility_promotion" in sql
    assert sql.replace(" ", "").endswith("'true',true)")


@pytest.mark.asyncio
async def test_demotion_never_touches_guc_and_demotes_relationships():
    uid, eid = uuid.uuid4(), uuid.uuid4()
    s = FakeSession({eid})
    result = await set_entity_visibility(s, uid, [eid], "private")
    assert s.kinds == ["lock", "entities", "rel_demote"]
    assert result == {"updated": 1, "unchanged": 0}


@pytest.mark.asyncio
async def test_every_statement_is_bound_to_the_calling_user():
    uid, eid = uuid.uuid4(), uuid.uuid4()
    for target in ("public", "private"):
        s = FakeSession({eid})
        await set_entity_visibility(s, uid, [eid], target)
        for kind, params in s.calls:
            if kind != "guc":
                assert params["uid"] == uid, kind
    for stmt in (
        svc._LOCK_CLOSURE,
        svc._UPDATE_ENTITIES,
        svc._PROMOTE_RELATIONSHIPS,
        svc._DEMOTE_RELATIONSHIPS,
    ):
        assert "user_id = :uid" in str(stmt)


@pytest.mark.asyncio
async def test_foreign_or_missing_id_raises_and_mutates_nothing():
    uid, mine = uuid.uuid4(), uuid.uuid4()
    foreign = uuid.uuid4()
    s = FakeSession({mine})  # `foreign` is not in the owned set
    with pytest.raises(EntityNotFoundError) as exc:
        await set_entity_visibility(s, uid, [mine, foreign], "public")
    assert s.kinds == ["lock"], "no GUC, no UPDATE once any id is not owned"
    assert str(foreign) not in str(exc.value) and str(mine) not in str(exc.value)


@pytest.mark.asyncio
async def test_foreign_and_missing_ids_are_indistinguishable():
    uid = uuid.uuid4()
    errs = []
    for _ in range(2):
        s = FakeSession(set())
        with pytest.raises(EntityNotFoundError) as exc:
            await set_entity_visibility(s, uid, [uuid.uuid4()], "public")
        errs.append((type(exc.value), str(exc.value), s.kinds))
    assert errs[0] == errs[1]


@pytest.mark.asyncio
async def test_rejection_warning_log_has_counts_not_entity_ids(caplog):
    uid, foreign = uuid.uuid4(), uuid.uuid4()
    with caplog.at_level(logging.INFO):
        with pytest.raises(EntityNotFoundError):
            await set_entity_visibility(FakeSession(set()), uid, [foreign], "public")
    text = " ".join(caplog.messages)
    assert str(uid) in text and "not_owned=1" in text
    assert str(foreign) not in text


@pytest.mark.asyncio
async def test_cap_exceeded_raises_before_any_db_call():
    s = FakeSession(set())
    with pytest.raises(ValueError, match=str(MAX_BULK_IDS)):
        await set_entity_visibility(s, uuid.uuid4(), _ids(MAX_BULK_IDS + 1), "public")
    assert s.calls == []


@pytest.mark.asyncio
async def test_exactly_cap_ids_is_accepted():
    ids = _ids(MAX_BULK_IDS)
    s = FakeSession(set(ids))
    result = await set_entity_visibility(s, uuid.uuid4(), ids, "public")
    assert result == {"updated": MAX_BULK_IDS, "unchanged": 0}


@pytest.mark.asyncio
async def test_cap_counts_raw_input_so_duplicates_cannot_bypass_via_padding():
    # 201 raw ids that dedupe to 1 are still rejected: the cap is on the payload.
    one = uuid.uuid4()
    s = FakeSession({one})
    with pytest.raises(ValueError):
        await set_entity_visibility(
            s, uuid.uuid4(), [one] * (MAX_BULK_IDS + 1), "public"
        )
    assert s.calls == []


@pytest.mark.asyncio
async def test_empty_list_returns_zeros_without_db_access():
    s = FakeSession(set())
    assert await set_entity_visibility(s, uuid.uuid4(), [], "public") == {
        "updated": 0,
        "unchanged": 0,
    }
    assert s.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["unpublished", "", "PUBLIC", "Private", " public", None, 1]
)
async def test_invalid_visibility_rejected_before_any_db_call(bad):
    s = FakeSession(set())
    with pytest.raises(ValueError):
        await set_entity_visibility(s, uuid.uuid4(), _ids(1), bad)  # type: ignore[arg-type]
    assert s.calls == []


@pytest.mark.asyncio
async def test_duplicates_are_deduplicated_and_counts_never_negative():
    uid, eid = uuid.uuid4(), uuid.uuid4()
    s = FakeSession({eid})
    result = await set_entity_visibility(s, uid, [eid, eid, eid], "private")
    assert result == {"updated": 1, "unchanged": 0}
    lock_ids = next(p["ids"] for k, p in s.calls if k == "lock")
    assert lock_ids == [eid]


@pytest.mark.asyncio
async def test_already_at_target_counts_as_unchanged_but_still_derives_relationships():
    uid = uuid.uuid4()
    a, b = uuid.uuid4(), uuid.uuid4()
    s = FakeSession({a, b}, changed={a})  # b already at target
    result = await set_entity_visibility(s, uid, [a, b], "public")
    assert result == {"updated": 1, "unchanged": 1}
    derive_ids = next(p["ids"] for k, p in s.calls if k == "rel_promote")
    assert set(derive_ids) == {a, b}, "repair pass must cover unchanged ids too"


@pytest.mark.asyncio
async def test_all_unchanged_returns_zero_updated():
    ids = _ids(3)
    s = FakeSession(set(ids), changed=set())
    result = await set_entity_visibility(s, uuid.uuid4(), ids, "public")
    assert result == {"updated": 0, "unchanged": 3}


@pytest.mark.asyncio
async def test_service_never_commits_or_rolls_back():
    eid = uuid.uuid4()
    for target in ("public", "private"):
        s = FakeSession({eid})
        await set_entity_visibility(s, uuid.uuid4(), [eid], target)
        s.commit.assert_not_awaited()
        s.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_db_error_during_update_propagates_unswallowed():
    eid = uuid.uuid4()
    s = FakeSession({eid})
    real = s.execute

    async def boom(stmt, params=None):
        if str(stmt).startswith("UPDATE ontology_entities"):
            raise RuntimeError("trigger rejected")
        return await real(stmt, params)

    s.execute = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="trigger rejected"):
        await set_entity_visibility(s, uuid.uuid4(), [eid], "public")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,direction", [("public", "promote"), ("private", "demote")]
)
async def test_audit_log_has_user_count_direction_only(caplog, target, direction):
    uid = uuid.uuid4()
    ids = _ids(2)
    s = FakeSession(set(ids))
    with caplog.at_level(logging.INFO):
        await set_entity_visibility(s, uid, ids, target)  # type: ignore[arg-type]
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1
    msg = infos[0].getMessage()
    assert (
        f"user_id={uid}" in msg and "count=2" in msg and f"direction={direction}" in msg
    )
    assert not any(str(i) in msg for i in ids)


@pytest.mark.asyncio
async def test_derive_selects_statement_by_direction():
    s = FakeSession(set())
    ids = _ids(1)
    await svc._derive_relationship_visibility(s, uuid.uuid4(), ids, "promote")
    await svc._derive_relationship_visibility(s, uuid.uuid4(), ids, "demote")
    assert s.kinds == ["rel_promote", "rel_demote"]
    assert (
        await svc._derive_relationship_visibility(s, uuid.uuid4(), [], "promote") == 0
    )
    assert len(s.calls) == 2


def test_promote_sql_requires_both_endpoints_public_and_demote_covers_both_ends():
    promote = str(svc._PROMOTE_RELATIONSHIPS)
    assert promote.count("visibility = 'public'") >= 3  # SET + source + target
    assert (
        "s.id = r.source_entity_id" in promote
        and "t.id = r.target_entity_id" in promote
    )
    demote = str(svc._DEMOTE_RELATIONSHIPS)
    assert (
        "source_entity_id = ANY(:ids)" in demote
        and "target_entity_id = ANY(:ids)" in demote
    )


def test_guc_name_appears_only_in_allowlisted_modules():
    src_root = Path(__file__).parent.parent / "src"
    allowed = {
        "ontology_visibility.py",
        "ontology_repository.py",
        "ontology_extract.py",
    }
    violations = [
        str(p.relative_to(src_root))
        for p in src_root.rglob("*.py")
        if p.name not in allowed
        and re.search(
            r"(set_config|SET\s+LOCAL)[^\n]*allow_visibility_promotion|"
            r"allow_visibility_promotion[^\n]*set_config",
            p.read_text(),
        )
    ]
    assert not violations, violations
