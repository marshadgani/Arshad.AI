"""Pure markdown renderer for the Obsidian vault export.

No DB, no git, no network. ``render_vault`` is the second line of defence
for the visibility invariant: it raises ``ValueError`` if any entity that is
not public reaches it, before any path or markdown is produced.

Every ``external_key``-derived path component goes through ``_sanitize_key``
— a raw key is never used as a filename. Frontmatter values are emitted as
JSON-quoted strings (valid YAML double-quoted scalars), so no YAML library is
needed and a key containing ``:`` or newlines cannot break out of its field.

Internal structure
------------------
``render_vault`` is composed of three named phases, each testable in isolation:

1. ``_build_export_paths`` — maps (type, key) → sanitized path, detects
   collisions.
2. ``_build_adjacency`` — derives bidirectional person↔project link sets from
   CONTRIBUTED_TO edges, dropping any edge whose endpoints are not in the
   exported set.
3. Note rendering loop — produces the final ``{filename: markdown}`` mapping.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ...models.ontology_vocabulary import CONTRIBUTED_TO, PERSON, PROJECT, PUBLIC

_SOURCE = "github"
_DIR_BY_TYPE = {PERSON: "People", PROJECT: "Projects"}
_DISALLOWED = re.compile(r"[^\w-]", re.ASCII)
_DASHES = re.compile(r"-{2,}")


@dataclass(frozen=True)
class Entity:
    id: str
    entity_type: str
    external_key: str
    visibility: str


@dataclass(frozen=True)
class Relationship:
    source_key: str
    source_type: str
    target_key: str
    target_type: str
    relationship_type: str


def _assert_no_traversal(segment: str) -> None:
    if ".." in segment or "\x00" in segment or "/" in segment or "\\" in segment:
        raise ValueError("unsafe path segment")


def _sanitize_key(key: str) -> str:
    cleaned = _DISALLOWED.sub("", key.replace("/", "-"))
    cleaned = _DASHES.sub("-", cleaned).strip("-")
    if not cleaned:
        raise ValueError("external_key sanitizes to an empty filename")
    _assert_no_traversal(cleaned)
    return cleaned


def _path(entity_type: str, key: str) -> str:
    return f"{_DIR_BY_TYPE[entity_type]}/{_sanitize_key(key)}"


def _frontmatter(entity: Entity) -> str:
    fields = {
        "type": entity.entity_type,
        "visibility": PUBLIC,
        "source": _SOURCE,
        "external_key": entity.external_key,
    }
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fields.items()]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _note(entity: Entity, heading: str, links: list[str]) -> str:
    body = f"\n## {heading}\n\n"
    if links:
        body += "\n".join(f"- [[{link}]]" for link in links) + "\n"
    title = f"# {_sanitize_key(entity.external_key)}\n"
    return _frontmatter(entity) + "\n" + title + body


def _build_export_paths(
    entities: list[Entity],
) -> dict[tuple[str, str], str]:
    """Map (entity_type, external_key) → relative file path (without .md suffix).

    Entities with unknown types (not in ``_DIR_BY_TYPE``) are silently dropped.
    Raises ``ValueError`` if two external_keys sanitize to the same filename.
    """
    exported: dict[tuple[str, str], str] = {}
    for entity in sorted(entities, key=lambda e: (e.entity_type, e.external_key)):
        if entity.entity_type not in _DIR_BY_TYPE:
            continue
        exported[(entity.entity_type, entity.external_key)] = _path(
            entity.entity_type, entity.external_key
        )
    paths = list(exported.values())
    if len(set(paths)) != len(paths):
        raise ValueError("two external_keys sanitize to the same filename")
    return exported


def _build_adjacency(
    relationships: list[Relationship],
    exported: dict[tuple[str, str], str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Derive bidirectional person↔project adjacency from CONTRIBUTED_TO edges.

    Only edges where both endpoints exist in ``exported`` are included, so no
    private entity's key can leak into a wikilink via a cross-visibility edge.
    Returns ``(projects_of, contributors_of)`` where each maps an external_key
    to the set of related external_keys.
    """
    projects_of: dict[str, set[str]] = {}
    contributors_of: dict[str, set[str]] = {}
    for rel in relationships:
        if (
            rel.relationship_type != CONTRIBUTED_TO
            or rel.source_type != PERSON
            or rel.target_type != PROJECT
        ):
            continue
        src = (rel.source_type, rel.source_key)
        dst = (rel.target_type, rel.target_key)
        if src not in exported or dst not in exported:
            continue
        projects_of.setdefault(rel.source_key, set()).add(rel.target_key)
        contributors_of.setdefault(rel.target_key, set()).add(rel.source_key)
    return projects_of, contributors_of


def render_vault(
    entities: list[Entity], relationships: list[Relationship]
) -> dict[str, str]:
    for entity in entities:
        if entity.visibility != PUBLIC:
            raise ValueError("refusing to render a non-public entity")

    exported = _build_export_paths(entities)
    projects_of, contributors_of = _build_adjacency(relationships, exported)

    files: dict[str, str] = {}
    for (etype, key), path in exported.items():
        entity = Entity("", etype, key, PUBLIC)
        if etype == PERSON:
            links = [
                exported[(PROJECT, k)]
                for k in sorted(projects_of.get(key, ()))
                if (PROJECT, k) in exported
            ]
            files[f"{path}.md"] = _note(entity, "Projects", links)
        else:
            links = [
                exported[(PERSON, k)]
                for k in sorted(contributors_of.get(key, ()))
                if (PERSON, k) in exported
            ]
            files[f"{path}.md"] = _note(entity, "Contributors", links)
    return files
