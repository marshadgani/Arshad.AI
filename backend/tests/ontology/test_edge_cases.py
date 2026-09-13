"""Edge-case and negative-path tests for the Obsidian Ontology Layer.

Covers TC-073 through TC-082.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.models.ontology import OntologyEntityNote
from src.services.ingestion.ontology.diff import blob_sha, plan_changes
from src.services.ingestion.ontology.identity import person_id_from_email
from src.services.ingestion.ontology.render import render_entity


def _plain_row(
    stable_entity_id: str = "event:edge",
    entity_type: str = "Event",
    domain: str = "calendar",
    display_name: str = "Edge Event",
    source_updated_at: datetime | None = None,
    tags: list | None = None,
    relationships: list | None = None,
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
    row.sync_state = "pending"
    row.blob_sha = ""
    row.vault_path = f"entities/{domain}/{entity_type}/{stable_entity_id}.md"
    return row


# ── TC-073 ─────────────────────────────────────────────────────────
def test_plan_changes_empty_input_empty_output():
    """Empty extractor result set → plan_changes returns no changes."""
    plan = plan_changes({}, {}, [])
    assert plan.changed_count == 0
    assert not plan


# ── TC-074 ─────────────────────────────────────────────────────────
def test_blob_sha_empty_content():
    """blob_sha must not crash on empty bytes."""
    sha = blob_sha(b"")
    assert len(sha) == 40


# ── TC-075 ─────────────────────────────────────────────────────────
def test_future_source_updated_at_no_error():
    """source_updated_at in the future should not cause rendering errors."""
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    row = _plain_row(source_updated_at=future)
    text = render_entity(row, {}, None)
    import yaml

    fm = yaml.safe_load(text.split("---")[1])
    assert "2099" in str(fm.get("updated", ""))


# ── TC-076 ─────────────────────────────────────────────────────────
def test_diff_plan_unchanged_count_property():
    """DiffPlan.unchanged_count = total rendered - changed."""
    text_a = "unchanged"
    sha_a = blob_sha(text_a.encode())
    text_b = "changed content new"

    rendered = {"a.md": text_a, "b.md": text_b}
    stored = {"a.md": sha_a, "b.md": "old_sha"}  # b changed
    plan = plan_changes(rendered, stored, [])
    assert plan.changed_count == 1
    assert plan.unchanged_count == 1


# ── TC-077 ─────────────────────────────────────────────────────────
def test_diff_plan_written_paths_excludes_deletes():
    """DiffPlan.written_paths must only include non-delete changes."""
    rendered = {"new.md": "new content"}
    stored = {"new.md": ""}  # triggers write
    rename_ops = [("old.md", "new.md")]  # triggers delete of old.md
    plan = plan_changes(rendered, stored, rename_ops)
    assert "new.md" in plan.written_paths
    assert "old.md" not in plan.written_paths


# ── TC-078 ─────────────────────────────────────────────────────────
def test_gmail_variant_normalization_cross_check():
    """Two differently-formatted gmail addresses that normalize to the same
    value must produce the same person_id (key cross-domain dedup check).
    """
    variants = [
        "john.doe+work@gmail.com",
        "JOHNDOE@GMAIL.COM",
        "j.o.h.n.d.o.e@gmail.com",
    ]
    ids = [person_id_from_email(v) for v in variants]
    assert len(set(ids)) == 1, f"Expected all same id, got: {ids}"


# ── TC-079 ─────────────────────────────────────────────────────────
def test_no_fuzzy_name_merging_different_emails():
    """Two Person records with different emails but identical display_name
    must remain distinct (person_id is based on email, not name).
    """
    id_a = person_id_from_email("alice@example.com")
    id_b = person_id_from_email("alice@different.com")
    assert id_a != id_b


# ── TC-080 ─────────────────────────────────────────────────────────
def test_render_entity_with_none_source_updated_at():
    """source_updated_at=None must produce null (not crash) in frontmatter updated field."""
    row = _plain_row(source_updated_at=None)
    row.source_updated_at = None  # explicit None
    text = render_entity(row, {}, None)
    import yaml

    fm = yaml.safe_load(text.split("---")[1])
    assert fm.get("updated") is None


# ── TC-081 ─────────────────────────────────────────────────────────
def test_person_entity_type_renders_without_error():
    """Person renderer must not raise even with no relationships."""
    row = _plain_row(
        stable_entity_id="person:aabbccdd12345678",
        entity_type="Person",
        domain="people",
    )
    text = render_entity(row, {}, None)
    assert "Person" in text or "person:" in text


# ── TC-082 ─────────────────────────────────────────────────────────
def test_repo_entity_type_renders_without_error():
    """Repo renderer must not raise even with no relationships."""
    row = _plain_row(
        stable_entity_id="repo:owner/myrepo",
        entity_type="Repo",
        domain="github",
        display_name="owner/myrepo",
    )
    text = render_entity(row, {}, None)
    assert "GitHub repository" in text or "repo:" in text
