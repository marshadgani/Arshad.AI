"""Pure unit tests for the vault renderer — no DB, no git, no network."""

from __future__ import annotations

import pytest
from src.services.ingestion.obsidian_vault_render import (
    Entity,
    Relationship,
    _sanitize_key,
    render_vault,
)


def _e(etype: str, key: str, visibility: str = "public") -> Entity:
    return Entity(id=key, entity_type=etype, external_key=key, visibility=visibility)


def _r(person: str, project: str) -> Relationship:
    return Relationship(person, "person", project, "project", "contributed_to")


def test_render_person_note_with_projects() -> None:
    files = render_vault(
        [_e("person", "octocat"), _e("project", "octo/hello")],
        [_r("octocat", "octo/hello")],
    )
    assert files["People/octocat.md"] == (
        "---\n"
        'type: "person"\n'
        'visibility: "public"\n'
        'source: "github"\n'
        'external_key: "octocat"\n'
        "---\n"
        "\n"
        "# octocat\n"
        "\n"
        "## Projects\n"
        "\n"
        "- [[Projects/octo-hello]]\n"
    )


def test_render_project_note_with_contributors() -> None:
    files = render_vault(
        [_e("person", "octocat"), _e("project", "octo/hello")],
        [_r("octocat", "octo/hello")],
    )
    note = files["Projects/octo-hello.md"]
    assert 'external_key: "octo/hello"' in note
    assert "## Contributors\n\n- [[People/octocat]]\n" in note


def test_render_empty_relationships() -> None:
    files = render_vault([_e("person", "solo")], [])
    assert files["People/solo.md"].endswith("## Projects\n\n")


def test_render_deterministic_order() -> None:
    ents = [
        _e("person", "b"),
        _e("person", "a"),
        _e("project", "x/y"),
        _e("project", "x/a"),
    ]
    rels = [_r("b", "x/y"), _r("b", "x/a"), _r("a", "x/y")]
    first = render_vault(ents, rels)
    second = render_vault(list(reversed(ents)), list(reversed(rels)))
    assert first == second
    assert first["People/b.md"].index("x-a") < first["People/b.md"].index("x-y")


def test_edge_to_unexported_entity_is_dropped() -> None:
    files = render_vault([_e("person", "octocat")], [_r("octocat", "secret/repo")])
    assert "secret" not in files["People/octocat.md"]


def test_sanitize_key_slash() -> None:
    assert _sanitize_key("owner/repo") == "owner-repo"


@pytest.mark.parametrize("key", ["../../etc/passwd", "..", "", "///", "\x00"])
def test_sanitize_key_path_traversal(key: str) -> None:
    try:
        out = _sanitize_key(key)
    except ValueError:
        return
    assert ".." not in out and "/" not in out and "\x00" not in out and out


def test_sanitize_key_traversal_result_is_flat() -> None:
    assert _sanitize_key("../../etc/passwd") == "etc-passwd"


def test_render_rejects_private_entity() -> None:
    with pytest.raises(ValueError):
        render_vault([_e("person", "ok"), _e("person", "hidden", "private")], [])


def test_filename_collision_raises() -> None:
    with pytest.raises(ValueError):
        render_vault([_e("project", "a/b"), _e("project", "a-b")], [])


def test_frontmatter_escapes_hostile_key() -> None:
    files = render_vault([_e("person", 'x"\nvisibility: private')], [])
    (note,) = files.values()
    assert note.count("\nvisibility:") == 1


def test_file_paths_correct() -> None:
    files = render_vault([_e("person", "p"), _e("project", "o/r")], [])
    assert set(files) == {"People/p.md", "Projects/o-r.md"}
