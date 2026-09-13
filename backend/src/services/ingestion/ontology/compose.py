"""Pass 2 orchestration — which rows become which notes.

``render.py`` knows how to turn ONE row into text. This module knows the
shape of a whole run's output: every non-MOC entity note, then one MOC
per domain, then the root index. Keeping that policy here rather than in
the pipeline means the full "what does this run write" question is
answerable from pure data — no DB session, no GitHub client — and the
pipeline is left holding only transaction and I/O decisions.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from ....models.ontology import OntologyEntityNote
from .catalogue import INDEX_ENTITY_ID, moc_entity_id
from .render import LinkMap, MissingLinkError, render_entity, render_index, render_moc

logger = logging.getLogger(__name__)

MOC_ENTITY_TYPE = "MOC"


@dataclass(frozen=True)
class ComposedNotes:
    """Full desired vault content for a run, keyed by vault path."""

    by_path: dict[str, str]
    unresolved_relationships: int

    @property
    def note_count(self) -> int:
        return len(self.by_path)


def compose(
    rows: list[OntologyEntityNote],
    link_map: LinkMap,
    domains: Iterable[str],
    *,
    unresolved_relationships: int = 0,
) -> ComposedNotes:
    """Render every note this run wants in the vault.

    ``unresolved_relationships`` seeds the tally with edges the resolver
    already dropped, so the caller reports one number rather than adding
    two together at the call site.
    """
    by_path: dict[str, str] = {}
    unresolved = unresolved_relationships
    rows_by_id = {row.stable_entity_id: row for row in rows}

    for row in rows:
        if row.entity_type == MOC_ENTITY_TYPE:
            continue
        try:
            by_path[row.vault_path] = render_entity(row, link_map, user_tail=None)
        except MissingLinkError:
            # Skipping one note is strictly better than failing the run:
            # every other entity still syncs, and the next run re-renders
            # this one once its link target is back in scope.
            unresolved += 1
            logger.warning(
                "ontology sync: skipping note with unresolvable link — %s",
                row.stable_entity_id,
            )

    domain_list = list(domains)
    for domain in domain_list:
        moc_row = rows_by_id.get(moc_entity_id(domain))
        if moc_row is None:
            continue
        members = [
            row
            for row in rows
            if row.domain == domain and row.entity_type != MOC_ENTITY_TYPE
        ]
        by_path[moc_row.vault_path] = render_moc(domain, members, link_map)

    index_row = rows_by_id.get(INDEX_ENTITY_ID)
    if index_row is not None:
        by_path[index_row.vault_path] = render_index(link_map, domain_list)

    return ComposedNotes(by_path=by_path, unresolved_relationships=unresolved)
