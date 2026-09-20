"""Ontology layer — slice 1: GitHub person/project entities + edges.

Two tables, ``ontology_entities`` and ``ontology_relationships``, form a
minimal knowledge graph derived from ingested GitHub activity. Scope for
this slice is deliberately narrow (FEAT-144 BLOCKER 2): ``entity_type``
is restricted to ``person`` / ``project`` and ``relationship_type`` to
``contributed_to`` only — Gmail/Calendar relationships need thread/event
entity types that don't exist yet and are a follow-up slice.

The vocabulary constants (``ENTITY_TYPES``, ``RELATIONSHIP_TYPES``,
``VISIBILITIES``) are NOT defined here — they live in
``.ontology_vocabulary``, derived from that module's source -> edge-shape
mapping table, and are re-exported below so this module stays the
import site every caller already expects. They are rendered into this
module's CHECK constraints AND must stay byte-identical to the raw CHECK
strings hard-coded in the migration
``o1l2m3n4a5b6_ontology_entities_and_relationships.py`` — that migration
is immutable per .claude/rules/database.md, so the two sources of truth
cannot resync themselves if they drift. A unit test
(``test_vocabulary_constants_match_migration`` in
``backend/tests/test_ontology_graph.py``) mechanically enforces this by
reading the migration file as text and asserting every constant appears
in it.

A visibility-ratchet trigger (defined in the migration, not here) blocks
promoting ``visibility`` from ``private`` to ``public`` unless the
transaction-local GUC ``app.allow_visibility_promotion`` is explicitly
set to ``'true'``. See the migration docstring for the full design.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampedMixin
from .ontology_vocabulary import (  # noqa: F401 — re-exported public API
    ENTITY_TYPES,
    PRIVATE,
    RELATIONSHIP_SCHEMA,
    RELATIONSHIP_TYPES,
    VISIBILITIES,
)


def _check_in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name)


class OntologyEntity(Base, TimestampedMixin):
    __tablename__ = "ontology_entities"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "entity_type",
            "external_key",
            name="uq_ontology_entities_user_type_key",
        ),
        UniqueConstraint("id", "user_id", name="uq_ontology_entities_id_user"),
        _check_in("entity_type", ENTITY_TYPES, "ck_ontology_entities_entity_type"),
        _check_in("visibility", VISIBILITIES, "ck_ontology_entities_visibility"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(10), nullable=False, default=PRIVATE, server_default=PRIVATE
    )
    classification_checked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class OntologyRelationship(Base, TimestampedMixin):
    __tablename__ = "ontology_relationships"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_entity_id",
            "relationship_type",
            "target_entity_id",
            name="uq_ontology_relationships_edge",
        ),
        ForeignKeyConstraint(
            ["source_entity_id", "user_id"],
            ["ontology_entities.id", "ontology_entities.user_id"],
            name="fk_ontology_relationships_source_entity",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_entity_id", "user_id"],
            ["ontology_entities.id", "ontology_entities.user_id"],
            name="fk_ontology_relationships_target_entity",
            ondelete="CASCADE",
        ),
        Index(
            "ix_ontology_relationships_target_entity_id",
            "user_id",
            "target_entity_id",
        ),
        _check_in(
            "relationship_type",
            RELATIONSHIP_TYPES,
            "ck_ontology_relationships_relationship_type",
        ),
        _check_in("visibility", VISIBILITIES, "ck_ontology_relationships_visibility"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    visibility: Mapped[str] = mapped_column(
        String(10), nullable=False, default=PRIVATE, server_default=PRIVATE
    )
