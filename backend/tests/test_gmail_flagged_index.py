"""Guards the partial index behind GET /api/v1/dashboard/tasks (FEAT-136).

``ix_ingested_gmail_flagged_user_occurred`` is a *partial* index. Postgres
only applies one when the query's WHERE clause is provably implied by the
index predicate, and that proof runs over the parsed expression tree — where
a bind parameter is not equal to a constant.

The natural ORM spelling of this filter,
``IngestedGmailThread.raw["_derived"]["labels"]``, compiles the JSON path
keys to bind parameters (``raw -> $2 -> $3``). Postgres cannot prove that
equal to ``raw -> '_derived' -> 'labels'``, so under a generic plan it
silently drops the partial index and falls back to a
``(user_id, occurred_at)`` scan with a residual filter — verified against
PostgreSQL 16: identical rows, no error, ~5x slower and scanning 2450
extra rows at a 1-in-50 flagged ratio, degrading further as the unflagged
majority of the mailbox grows.

Nothing about that failure is observable from the response, so these tests
assert on the compiled SQL instead. They are the only thing standing
between a well-meaning "use the ORM accessor" refactor and a silent
performance regression in production.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy.dialects import postgresql
from src.models.ingested import GMAIL_FLAGGED_LABELS_PREDICATE, IngestedGmailThread
from src.services.dashboard import queries


class _CapturingSession:
    """Captures the statement instead of executing it — these tests assert
    on generated SQL, so no database is involved."""

    def __init__(self) -> None:
        self.stmt: Any = None

    async def execute(self, stmt: Any) -> Any:
        self.stmt = stmt
        return _EmptyResult()


class _EmptyResult:
    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return []


def _compiled_query_sql() -> str:
    session = _CapturingSession()
    asyncio.run(queries.fetch_flagged_gmail_threads(session, uuid.uuid4()))
    return str(session.stmt.compile(dialect=postgresql.asyncpg.dialect()))


def _index_predicate_sql() -> str:
    index = next(
        ix
        for ix in IngestedGmailThread.__table__.indexes
        if ix.name == "ix_ingested_gmail_flagged_user_occurred"
    )
    return str(index.dialect_options["postgresql"]["where"])


def test_query_where_clause_contains_the_index_predicate_verbatim():
    """The load-bearing assertion: the exact predicate string that defines
    the partial index must appear verbatim in the query's WHERE clause.

    Anything less than a verbatim match (reordered conjuncts, a rewritten
    JSON path, bind parameters) risks defeating Postgres' implication
    proof and losing the index.
    """
    assert GMAIL_FLAGGED_LABELS_PREDICATE in _compiled_query_sql()


def test_index_predicate_is_the_shared_constant():
    """The index is defined from the same constant, so the two cannot drift
    apart — this pins that wiring, not just the current string value."""
    assert _index_predicate_sql() == GMAIL_FLAGGED_LABELS_PREDICATE


def test_json_path_keys_are_literals_not_bind_parameters():
    """The specific regression: '_derived'/'labels' must be SQL literals.
    Compiled as bind parameters they'd render as `raw -> $2 -> $3`."""
    sql = _compiled_query_sql()
    assert "raw->'_derived'->'labels'" in sql
    assert "raw -> $" not in sql


def test_user_id_is_still_a_bound_parameter():
    """The literal SQL fragment must not have dragged user_id inline with
    it — that is both an injection surface and a plan-cache buster
    (.claude/rules/database.md)."""
    sql = _compiled_query_sql()
    assert "ingested_gmail_threads.user_id = $1" in sql


def test_predicate_carries_no_interpolation_placeholder():
    """The constant is embedded as raw SQL, so it must never grow an
    f-string/format placeholder that a caller could fill."""
    assert "%s" not in GMAIL_FLAGGED_LABELS_PREDICATE
    assert "{" not in GMAIL_FLAGGED_LABELS_PREDICATE


def test_both_conjuncts_present_type_guard_and_business_filter():
    """jsonb_typeof(...)='array' is the type guard that stops
    jsonb_array_length raising on a scalar payload; the > 0 clause is the
    business filter that keeps empty-labelled threads out of /tasks.
    Dropping either changes behaviour, not just performance."""
    sql = _compiled_query_sql()
    assert "jsonb_typeof(raw->'_derived'->'labels') = 'array'" in sql
    assert "jsonb_array_length(raw->'_derived'->'labels') > 0" in sql
