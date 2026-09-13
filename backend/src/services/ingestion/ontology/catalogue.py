"""The vault's navigation spine — MOC and root-index entity identities.

These are entities the ontology layer invents rather than extracts, so
they have no extractor to own them. Keeping their ids/titles here (next
to the other pure entity definitions) rather than in the orchestrator
means "what MOCs exist and what are they called" is one import away for
any pass, and the orchestrator stays a wiring file.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import EntityRecord

INDEX_ENTITY_ID = "moc:index"
INDEX_DISPLAY_NAME = "Arshad.AI Index"
INDEX_DOMAIN = "root"
MOC_TAG = "arshad-ai/moc"


def moc_entity_id(domain: str) -> str:
    return f"moc:{domain}"


def moc_display_name(domain: str) -> str:
    return f"{domain.title()} MOC"


def navigation_records(domains: Iterable[str]) -> list[EntityRecord]:
    """MOC + root index as first-class tracked entities.

    The caller appends these AFTER the ``max_entities`` ceiling is
    applied, so the navigation spine is never what gets cut. Tracking
    them as real ``OntologyEntityNote`` rows (rather than synthesising
    their paths at render time) is what lets the persist pass store their
    ``blob_sha`` — without a stored SHA the diff pass has nothing to
    compare against and every run re-commits the MOCs unchanged, i.e. an
    empty vault commit per run, which is exactly the duplicate-commit
    churn FEAT-141 point 5 exists to prevent.
    """
    records = [
        EntityRecord(
            entity_type="MOC",
            stable_entity_id=moc_entity_id(domain),
            display_name=moc_display_name(domain),
            domain=domain,
            source_id=domain,
            source_updated_at=None,
            tags=[MOC_TAG],
        )
        for domain in domains
    ]
    records.append(
        EntityRecord(
            entity_type="MOC",
            stable_entity_id=INDEX_ENTITY_ID,
            display_name=INDEX_DISPLAY_NAME,
            domain=INDEX_DOMAIN,
            source_id="index",
            source_updated_at=None,
            tags=[MOC_TAG],
        )
    )
    return records
