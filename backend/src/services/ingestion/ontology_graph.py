"""Pure, DB-free derivation of the GitHub person/project graph.

No SQLAlchemy, no async, no I/O, no session. Takes the row shape the
extraction sweep actually returns (``list[dict[str, Any]]``) and derives
the set of person entities, project entities, and ``contributed_to``
edges between them. Fully unit-testable in milliseconds without
Postgres.

Edge labels and entity-type names are NOT literals here — they come from
``models.ontology_vocabulary``, the same mapping table the CHECK
constraints are derived from, so this module cannot emit an edge the
database would reject. That module imports nothing, so depending on it
costs this one none of its purity.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from ...models.ontology_vocabulary import GITHUB_CONTRIBUTION


class EdgeTuple(NamedTuple):
    """A single derived edge. Named fields make transposing person/project
    a type error rather than a silent positional bug."""

    person_key: str
    relationship: str
    project_key: str


class DerivedGraph(NamedTuple):
    persons: set[str]
    projects: set[str]
    edges: list[EdgeTuple]
    skipped_no_author: int


def _extract_login(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    user = raw.get("user")
    if not isinstance(user, dict):
        return None
    login = user.get("login")
    if not isinstance(login, str) or not login:
        return None
    return login


def derive_graph(rows: list[dict[str, Any]]) -> DerivedGraph:
    persons: set[str] = set()
    projects: set[str] = set()
    edges: list[EdgeTuple] = []
    skipped_no_author = 0

    for row in rows:
        raw = row.get("raw")
        login = _extract_login(raw)
        if login is None:
            skipped_no_author += 1
            continue

        provider_id = row.get("provider_id") or ""
        project_key = provider_id.split("#", 1)[0]
        if not project_key:
            skipped_no_author += 1
            continue

        persons.add(login)
        projects.add(project_key)
        edges.append(
            EdgeTuple(
                person_key=login,
                relationship=GITHUB_CONTRIBUTION.relationship_type,
                project_key=project_key,
            )
        )

    return DerivedGraph(
        persons=persons,
        projects=projects,
        edges=edges,
        skipped_no_author=skipped_no_author,
    )
