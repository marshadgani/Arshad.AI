"""Unit tests — render.py byte-determinism, frontmatter structure, wikilinks.

Covers TC-011 through TC-027.
All tests are pure unit tests with zero DB/network I/O.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import yaml
from src.models.ontology import OntologyEntityNote
from src.services.ingestion.ontology.render import (
    MANAGED_END,
    MANAGED_START,
    MissingLinkError,
    render_entity,
    render_moc,
)


def _entity_row(
    stable_entity_id: str = "event:abc",
    entity_type: str = "Event",
    domain: str = "calendar",
    display_name: str = "Team Standup",
    source_updated_at: datetime | None = None,
    tags: list[str] | None = None,
    relationships: list[dict[str, str]] | None = None,
    sync_state: str = "pending",
) -> OntologyEntityNote:
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = uuid.uuid4()
    row.stable_entity_id = stable_entity_id
    row.entity_type = entity_type
    row.domain = domain
    row.display_name = display_name
    row.source_updated_at = source_updated_at or datetime(
        2024, 1, 1, tzinfo=timezone.utc
    )
    row.tags = tags or []
    row.relationships = relationships or []
    row.sync_state = sync_state
    row.blob_sha = ""
    row.vault_path = f"entities/{domain}/{entity_type}/{stable_entity_id}.md"
    return row


# ── TC-011 ─────────────────────────────────────────────────────────
def test_render_entity_byte_deterministic():
    """render_entity called twice with same inputs produces identical bytes."""
    row = _entity_row()
    link_map: dict[str, tuple[str, str]] = {}
    result_a = render_entity(row, link_map, None)
    result_b = render_entity(row, link_map, None)
    assert result_a == result_b


# ── TC-012 ─────────────────────────────────────────────────────────
def test_render_entity_frontmatter_keys_sorted():
    """YAML frontmatter keys must be alphabetically sorted (sort_keys=True)."""
    row = _entity_row()
    text = render_entity(row, {}, None)
    # Extract frontmatter block
    fm_text = text.split("---")[1]
    loaded = yaml.safe_load(fm_text)
    keys = list(loaded.keys())
    assert keys == sorted(keys)


# ── TC-013 ─────────────────────────────────────────────────────────
def test_render_entity_required_frontmatter_fields_present():
    row = _entity_row()
    text = render_entity(row, {}, None)
    fm_text = text.split("---")[1]
    fm = yaml.safe_load(fm_text)
    for key in (
        "uid",
        "type",
        "domain",
        "source",
        "source_id",
        "tags",
        "aliases",
        "updated",
        "status",
    ):
        assert key in fm, f"Missing frontmatter key: {key}"


# ── TC-014 ─────────────────────────────────────────────────────────
def test_render_entity_last_synced_not_in_frontmatter():
    """Regression: last_synced must NEVER appear in frontmatter — it would
    change the blob SHA on every run and destroy idempotent-skip."""
    row = _entity_row()
    text = render_entity(row, {}, None)
    fm_text = text.split("---")[1]
    fm = yaml.safe_load(fm_text)
    assert "last_synced" not in fm
    assert "last_synced_at" not in fm


# ── TC-015 ─────────────────────────────────────────────────────────
def test_render_entity_managed_region_markers_present():
    row = _entity_row()
    text = render_entity(row, {}, None)
    assert MANAGED_START in text
    assert MANAGED_END in text
    assert text.index(MANAGED_START) < text.index(MANAGED_END)


# ── TC-016 ─────────────────────────────────────────────────────────
def test_render_entity_user_tail_preserved():
    row = _entity_row()
    tail = "\n## My Notes\nSome personal insight."
    text = render_entity(row, {}, tail)
    assert tail in text
    # tail appears AFTER managed end
    assert text.index(MANAGED_END) < text.index("My Notes")


# ── TC-017 ─────────────────────────────────────────────────────────
def test_render_entity_no_tail_no_extra_markers():
    row = _entity_row()
    text = render_entity(row, {}, None)
    # No dangling marker or extra section beyond MANAGED_END
    after_end = text.split(MANAGED_END, 1)[1]
    assert after_end.strip() == ""


# ── TC-018 ─────────────────────────────────────────────────────────
def test_render_entity_missing_link_raises_error():
    """A relationship whose target is absent from link_map must raise MissingLinkError."""
    row = _entity_row(
        entity_type="Event",
        relationships=[
            {"rel": "attended_by", "target_entity_id": "person:deadbeef01234567"}
        ],
    )
    # Empty link_map — target not present
    with pytest.raises(MissingLinkError):
        render_entity(row, {}, None)


# ── TC-019 ─────────────────────────────────────────────────────────
def test_render_entity_wikilink_present_when_in_link_map():
    row = _entity_row(
        entity_type="Event",
        relationships=[
            {"rel": "attended_by", "target_entity_id": "person:aabbccdd11223344"}
        ],
    )
    link_map = {
        "person:aabbccdd11223344": (
            "entities/people/Person/person:aabbccdd11223344.md",
            "Alice",
        )
    }
    text = render_entity(row, link_map, None)
    assert "[[" in text and "]]" in text


# ── TC-020 ─────────────────────────────────────────────────────────
def test_render_entity_thread_links_participants():
    row = _entity_row(
        stable_entity_id="thread:gmail_abc",
        entity_type="Thread",
        domain="email",
        relationships=[
            {"rel": "participant", "target_entity_id": "person:aabbccdd00112233"}
        ],
    )
    link_map = {
        "person:aabbccdd00112233": (
            "entities/people/Person/person:aabbccdd00112233.md",
            "Bob",
        )
    }
    text = render_entity(row, link_map, None)
    assert "Participants" in text
    assert "[[" in text


# ── TC-021 ─────────────────────────────────────────────────────────
def test_render_entity_yaml_safe_with_special_chars():
    """display_name containing YAML-unsafe chars must not corrupt frontmatter."""
    row = _entity_row(display_name='Event: "A:B" — C & D')
    text = render_entity(row, {}, None)
    fm_text = text.split("---")[1]
    # Must parse without error
    fm = yaml.safe_load(fm_text)
    assert isinstance(fm, dict)


# ── TC-022 ─────────────────────────────────────────────────────────
def test_render_moc_sorts_by_recency_then_entity_id():
    """MOC renderer: entities sorted source_updated_at DESC, stable_entity_id ASC."""
    t1 = datetime(2024, 6, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 7, 1, tzinfo=timezone.utc)  # more recent
    rows = [
        _entity_row(stable_entity_id="event:zzz", source_updated_at=t1),
        _entity_row(stable_entity_id="event:aaa", source_updated_at=t2),
    ]
    link_map = {
        "event:zzz": ("entities/calendar/Event/event:zzz.md", "Old Event"),
        "event:aaa": ("entities/calendar/Event/event:aaa.md", "New Event"),
    }
    text = render_moc("calendar", rows, link_map)
    idx_aaa = text.index("event:aaa")
    idx_zzz = text.index("event:zzz")
    assert idx_aaa < idx_zzz, "More recent entity should appear first"


# ── TC-023 ─────────────────────────────────────────────────────────
def test_render_moc_truncates_at_50():
    """MOC must list at most 50 entities even with 51+ input rows."""
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        _entity_row(
            stable_entity_id=f"event:evt_{i:03d}",
            display_name=f"Event {i}",
            source_updated_at=base_time,
        )
        for i in range(60)
    ]
    link_map = {
        f"event:evt_{i:03d}": (
            f"entities/calendar/Event/event:evt_{i:03d}.md",
            f"Event {i}",
        )
        for i in range(60)
    }
    text = render_moc("calendar", rows, link_map)
    # Count wikilinks — each entity adds exactly one [[...|...]] or [[...]]
    wikilink_count = text.count("[[")
    assert wikilink_count <= 50


# ── TC-024 ─────────────────────────────────────────────────────────
def test_render_moc_contains_dataview_block():
    rows = [_entity_row()]
    link_map = {"event:abc": ("entities/calendar/Event/event:abc.md", "Team Standup")}
    text = render_moc("calendar", rows, link_map)
    assert "```dataview" in text
    assert "calendar" in text  # domain filter in query


# ── TC-025 ─────────────────────────────────────────────────────────
def test_render_entity_tags_include_domain_prefix():
    """tags array in frontmatter must include arshad-ai/{domain}."""
    row = _entity_row(domain="calendar", tags=["important"])
    text = render_entity(row, {}, None)
    fm = yaml.safe_load(text.split("---")[1])
    assert "arshad-ai/calendar" in fm["tags"]


# ── TC-026 ─────────────────────────────────────────────────────────
def test_render_entity_archived_status_in_frontmatter():
    row = _entity_row(sync_state="archived")
    text = render_entity(row, {}, None)
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["status"] == "archived"


# ── TC-027 ─────────────────────────────────────────────────────────
def test_render_entity_person_body_contains_dataview():
    row = _entity_row(
        entity_type="Person",
        domain="people",
        stable_entity_id="person:aabbccdd12345678",
    )
    text = render_entity(row, {}, None)
    assert "```dataview" in text
