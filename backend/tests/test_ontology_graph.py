"""Unit tests for backend/src/services/ingestion/ontology_graph.py.

These tests are pure-function: no database, no @pytest.mark.pg, no fixtures
beyond plain dict literals.  They must run in milliseconds and be safe in CI
without a Postgres service.

Covers DEL-004 (pure derivation) and the vocabulary-drift guard (DEL-002
immutability cross-check).
"""

from __future__ import annotations

from pathlib import Path

from src.models.ontology import ENTITY_TYPES, RELATIONSHIP_TYPES, VISIBILITIES
from src.services.ingestion.ontology_graph import (
    MAX_EXTERNAL_KEY_LEN,
    EdgeTuple,
    derive_graph,
)

# ── helpers ────────────────────────────────────────────────────────────────────


def _row(
    login: str = "alice",
    provider_id: str = "owner/repo#42",
    occurred_at: str = "2024-01-01T00:00:00Z",
) -> dict:
    """Minimal GitHub activity row shaped exactly like the sweep query's row
    mapping: the login lives under ``raw.user.login`` (raw is the ingested
    GitHub API payload), not at the row's top level — see
    ``ontology_graph._extract_login`` and ``github.py``'s ingestion of
    ``raw``."""
    return {
        "raw": {"user": {"login": login}},
        "provider_id": provider_id,
        "occurred_at": occurred_at,
    }


# ── REQ-001 — Extract GitHub person entities ───────────────────────────────────


def test_derive_persons():
    """Rows with distinct logins produce a persons set of unique logins."""
    rows = [_row("alice"), _row("bob"), _row("alice")]  # alice duplicated
    graph = derive_graph(rows)
    assert graph.persons == {"alice", "bob"}, (
        f"Expected {{alice, bob}}, got {graph.persons}"
    )


def test_skip_no_author():
    """Row missing 'user' key entirely increments skipped_no_author and contributes no person/edge."""
    rows = [{"provider_id": "owner/repo#1", "occurred_at": "2024-01-01T00:00:00Z"}]
    graph = derive_graph(rows)
    assert graph.skipped_no_author == 1
    assert len(graph.persons) == 0
    assert len(graph.edges) == 0


def test_skip_none_login():
    """Row with user={'login': None} increments skipped_no_author, doesn't raise, doesn't add None."""
    rows = [
        {
            "user": {"login": None},
            "provider_id": "owner/repo#1",
            "occurred_at": "2024-01-01T00:00:00Z",
        }
    ]
    graph = derive_graph(rows)
    assert graph.skipped_no_author == 1
    assert None not in graph.persons


# ── REQ-002 — Extract GitHub project entities ──────────────────────────────────


def test_derive_projects():
    """provider_id 'owner/repo#123' -> project key 'owner/repo' via split('#',1)[0]."""
    rows = [_row(provider_id="owner/repo#123")]
    graph = derive_graph(rows)
    assert "owner/repo" in graph.projects


def test_derive_project_no_hash():
    """provider_id with no '#' is used as-is as the project key."""
    rows = [_row(provider_id="owner/repo")]
    graph = derive_graph(rows)
    assert "owner/repo" in graph.projects


# ── REQ-003 — Derive person→project relationships ──────────────────────────────


def test_derive_edges():
    """Each row yields EdgeTuple(person_key=login, relationship='contributed_to', project_key=project)."""
    rows = [_row("alice", "owner/repo#1")]
    graph = derive_graph(rows)
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.person_key == "alice"
    assert edge.relationship == "contributed_to"
    assert edge.project_key == "owner/repo"


def test_edge_tuple_fields_named():
    """EdgeTuple constructed positionally in wrong order fails equality against named construction."""
    correct = EdgeTuple(
        person_key="alice", relationship="contributed_to", project_key="owner/repo"
    )
    wrong_order = EdgeTuple(
        person_key="contributed_to", relationship="alice", project_key="owner/repo"
    )
    assert correct != wrong_order, "Named-field ordering must be enforced"


# ── Oversized external_key ──────────────────────────────────────────────────────


def test_skip_oversized_login():
    """A login longer than MAX_EXTERNAL_KEY_LEN is dropped and counted,
    not silently truncated or passed through to violate the DB column."""
    rows = [_row(login="x" * (MAX_EXTERNAL_KEY_LEN + 1))]
    graph = derive_graph(rows)
    assert graph.skipped_oversized_key == 1
    assert len(graph.persons) == 0
    assert len(graph.edges) == 0


def test_skip_oversized_project_key():
    """A derived project_key (from provider_id) longer than
    MAX_EXTERNAL_KEY_LEN is dropped and counted the same way."""
    rows = [_row(provider_id="x" * (MAX_EXTERNAL_KEY_LEN + 1) + "#1")]
    graph = derive_graph(rows)
    assert graph.skipped_oversized_key == 1
    assert len(graph.projects) == 0
    assert len(graph.edges) == 0


def test_key_at_exact_limit_is_not_skipped():
    """A login of exactly MAX_EXTERNAL_KEY_LEN chars fits the column and
    must NOT be skipped — only strictly-over-the-limit values are."""
    rows = [_row(login="x" * MAX_EXTERNAL_KEY_LEN)]
    graph = derive_graph(rows)
    assert graph.skipped_oversized_key == 0
    assert len(graph.persons) == 1


# ── Deduplication ──────────────────────────────────────────────────────────────


def test_deduplication():
    """10 rows from 2 people / 2 projects produce persons/projects sets of size 2 each."""
    rows = [
        _row("alice", "org/proj-a#1"),
        _row("bob", "org/proj-b#2"),
    ] * 5
    graph = derive_graph(rows)
    assert len(graph.persons) == 2
    assert len(graph.projects) == 2


# ── BLOCKER 2 vocabulary drift guard ──────────────────────────────────────────


def test_vocabulary_constants_match_migration():
    """Every value in ENTITY_TYPES, RELATIONSHIP_TYPES, VISIBILITIES appears
    as a literal substring in the immutable Alembic migration file."""
    versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*ontology*"))
    assert migration_files, (
        f"No ontology migration file found in {versions_dir}. "
        "Expected a file matching '*ontology*'."
    )
    migration_text = migration_files[0].read_text(encoding="utf-8")

    all_vocab = list(ENTITY_TYPES) + list(RELATIONSHIP_TYPES) + list(VISIBILITIES)
    for value in all_vocab:
        assert value in migration_text, (
            f"Vocabulary constant '{value}' not found in migration file "
            f"{migration_files[0].name}. "
            "ORM constants and migration CHECK constraints have drifted."
        )
