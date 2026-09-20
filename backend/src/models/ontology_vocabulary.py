"""Ontology vocabulary — single source of truth for the ontology's
allowed ``entity_type`` / ``relationship_type`` / ``visibility`` strings,
and for the source -> edge-shape mapping table those strings are derived
from (BLOCKER 2 of the FEAT-144 retry requirement).

This module imports nothing — not SQLAlchemy, not the app. That keeps it
safe to import from the deliberately DB-free derivation layer.
"""

from __future__ import annotations

from typing import Final, NamedTuple

PERSON: Final = "person"
PROJECT: Final = "project"

CONTRIBUTED_TO: Final = "contributed_to"

PRIVATE: Final = "private"
PUBLIC: Final = "public"


class RelationshipRule(NamedTuple):
    source: str
    source_entity_type: str
    relationship_type: str
    target_entity_type: str


GITHUB_CONTRIBUTION: Final = RelationshipRule(
    source="github",
    source_entity_type=PERSON,
    relationship_type=CONTRIBUTED_TO,
    target_entity_type=PROJECT,
)

RELATIONSHIP_SCHEMA: Final[tuple[RelationshipRule, ...]] = (GITHUB_CONTRIBUTION,)

ENTITY_TYPES: Final[tuple[str, ...]] = tuple(
    sorted(
        {rule.source_entity_type for rule in RELATIONSHIP_SCHEMA}
        | {rule.target_entity_type for rule in RELATIONSHIP_SCHEMA}
    )
)

RELATIONSHIP_TYPES: Final[tuple[str, ...]] = tuple(
    sorted({rule.relationship_type for rule in RELATIONSHIP_SCHEMA})
)

VISIBILITIES: Final[tuple[str, ...]] = (PRIVATE, PUBLIC)
