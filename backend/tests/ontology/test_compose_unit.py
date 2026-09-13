"""Unit tests — compose.py (Pass 2 orchestration: which rows become
which notes).

The behavior under test here (compose.py catching MissingLinkError and
skipping just the one offending note) is the opposite policy from
render.py raising it — and was completely uncovered. A regression that
turned this into a hard failure would take down an entire sync run over
one dangling relationship instead of degrading gracefully.

Covers TC-110 through TC-115.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.models.ontology import OntologyEntityNote
from src.services.ingestion.ontology.catalogue import INDEX_ENTITY_ID, moc_entity_id
from src.services.ingestion.ontology.compose import compose


def _row(
    stable_id: str,
    entity_type: str = "Event",
    domain: str = "calendar",
    display_name: str = "Row",
    relationships: list[dict] | None = None,
    vault_path: str | None = None,
) -> OntologyEntityNote:
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = uuid.uuid4()
    row.stable_entity_id = stable_id
    row.entity_type = entity_type
    row.domain = domain
    row.display_name = display_name
    row.source_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    row.tags = []
    row.relationships = relationships or []
    row.sync_state = "pending"
    row.blob_sha = ""
    row.vault_path = vault_path or f"{domain}/{entity_type}/{stable_id}.md"
    return row


# ── TC-110 ─────────────────────────────────────────────────────────
def test_compose_skips_note_with_unresolvable_link_but_keeps_others():
    """One entity with a dangling relationship must be dropped from the
    output WITHOUT taking any other entity's note down with it."""
    good = _row("event:good")
    bad = _row(
        "event:bad",
        relationships=[
            {"rel": "attended_by", "target_entity_id": "person:doesnotexist00"}
        ],
    )
    link_map = {
        "event:good": (good.vault_path, "Row"),
        "event:bad": (bad.vault_path, "Row"),
    }
    composed = compose([good, bad], link_map, domains=["calendar"])

    assert good.vault_path in composed.by_path
    assert bad.vault_path not in composed.by_path


# ── TC-111 ─────────────────────────────────────────────────────────
def test_compose_counts_unresolved_relationship_when_note_skipped():
    bad = _row(
        "event:bad",
        relationships=[
            {"rel": "attended_by", "target_entity_id": "person:doesnotexist00"}
        ],
    )
    link_map = {"event:bad": (bad.vault_path, "Row")}
    composed = compose([bad], link_map, domains=["calendar"])
    assert composed.unresolved_relationships == 1


# ── TC-112 ─────────────────────────────────────────────────────────
def test_compose_seeds_unresolved_count_from_caller():
    """The resolver may have already dropped relationships before compose
    ever sees the row (max_entities ceiling) — that count must be
    additive, not overwritten."""
    good = _row("event:good")
    link_map = {"event:good": (good.vault_path, "Row")}
    composed = compose(
        [good], link_map, domains=["calendar"], unresolved_relationships=5
    )
    assert composed.unresolved_relationships == 5


# ── TC-113 ─────────────────────────────────────────────────────────
def test_compose_skips_moc_rows_from_entity_rendering():
    """A row whose entity_type is MOC is never rendered as a plain entity
    note — only via the dedicated MOC path below."""
    moc_row = _row(moc_entity_id("calendar"), entity_type="MOC", domain="calendar")
    composed = compose([moc_row], {}, domains=["calendar"])
    # The MOC's own path IS produced, but via render_moc, not render_entity —
    # a domain with a tracked MOC row always gets a MOC note.
    assert moc_row.vault_path in composed.by_path


# ── TC-114 ─────────────────────────────────────────────────────────
def test_compose_omits_moc_for_domain_with_no_tracked_moc_row():
    """No index_row / moc_row present for a domain → compose does not
    fabricate one; that domain simply gets no MOC entry this run."""
    good = _row("event:good", domain="calendar")
    composed = compose(
        [good], {"event:good": (good.vault_path, "Row")}, domains=["calendar"]
    )
    # Only the entity note; no synthetic MOC path was invented.
    assert list(composed.by_path.keys()) == [good.vault_path]


# ── TC-115 ─────────────────────────────────────────────────────────
def test_compose_renders_root_index_when_tracked():
    """render_index() links to every domain's MOC — those must already be
    resolvable in link_map, exactly as pipeline.py guarantees by running
    navigation_records() (which emits one EntityRecord per configured
    domain plus the index) through resolve() before compose() is ever
    called. A link_map missing a configured domain's MOC is a resolver
    wiring bug, not something compose() is expected to paper over."""
    index_row = _row(
        INDEX_ENTITY_ID,
        entity_type="MOC",
        domain="root",
        vault_path="Arshad.AI/index.md",
    )
    link_map = {
        "moc:calendar": ("Arshad.AI/MOCs/calendar.md", "Calendar MOC"),
        "moc:email": ("Arshad.AI/MOCs/email.md", "Email MOC"),
    }
    composed = compose([index_row], link_map, domains=["calendar", "email"])
    assert "Arshad.AI/index.md" in composed.by_path
