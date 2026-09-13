"""Pure data shared by every pass. Zero SQLAlchemy/httpx imports —
this module must stay importable (and testable) without a DB or network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RelationshipRef:
    """One directed edge from the owning entity to another, resolved to
    a wikilink by the renderer once ``target_entity_id`` exists in the
    resolver's link_map. ``rel`` is a short verb phrase, e.g.
    'attended_by', 'authored_by', 'in_repo'."""

    rel: str
    target_entity_id: str


@dataclass(frozen=True)
class EntityRecord:
    """One entity emitted by an extractor, before identity resolution.

    ``stable_entity_id`` may be provisional here (e.g. an extractor's
    best-guess email-based Person ID) — the resolver is the single
    source of truth for the final ID and may re-derive it, but
    extractors should compute it the same way the resolver does so the
    common case needs no re-derivation.
    """

    entity_type: str
    stable_entity_id: str
    display_name: str
    domain: str
    source_id: str
    source_updated_at: datetime | None
    relationships: list[RelationshipRef] = field(default_factory=list)
    raw_fields: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


class Recency(Protocol):
    """Structural type of anything orderable by "most recently updated".

    Satisfied by both ``EntityRecord`` (pre-resolution) and
    ``OntologyEntityNote`` (post-resolution), which is why the ordering
    helper below can be shared by the extract budget and the MOC
    renderer instead of each re-deriving the same tie-break rule.
    """

    source_updated_at: datetime | None
    stable_entity_id: str


def recency_desc_key(item: Recency) -> tuple[float, str]:
    """Sort key for "most recently updated first, ties by id ascending".

    Undated entities sort last among themselves but deterministically, so
    repeated runs over unchanged data always pick the same winners when a
    cap or a MOC list has to cut somewhere.
    """
    updated = item.source_updated_at
    return (-(updated.timestamp() if updated else 0), item.stable_entity_id)
