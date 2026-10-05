"""Pure-function tests for obsidian_vault_render (no DB, git, or network)."""
from __future__ import annotations

import json
import random

import re

import pytest

from src.services.ingestion import obsidian_vault_render as r
from src.services.ingestion.obsidian_vault_render import (
    Entity,
    Relationship,
    render_vault,
)


def _person(key):
    return Entity("id-" + key, "person", key, "public")


def _project(key):
    return Entity("id-" + key, "project", key, "public")


def _edge(person_key, project_key, rtype="contributed_to", stype="person", ttype="project"):
    return Relationship(person_key, stype, project_key, ttype, rtype, "public")


def _frontmatter(content):
    assert content.startswith("---\n")
    block = content[4 : content.index("\n---\n", 4)]
    return {k: json.loads(v) for k, v in (ln.split(": ", 1) for ln in block.split("\n"))}


def test_person_note_exact_output():
    out = render_vault([_person("alice"), _project("o/r")], [_edge("alice", "o/r")])
    assert out["People/alice.md"] == (
        '---\ntype: "person"\nvisibility: "public"\nsource: "github"\n'
        'external_key: "alice"\n---\n\n# alice\n\n## Projects\n\n- [[Projects/o-r]]\n'
    )


def test_project_note_exact_output_keeps_raw_key_in_frontmatter():
    out = render_vault([_person("alice"), _project("o/r")], [_edge("alice", "o/r")])
    assert out["Projects/o-r.md"] == (
        '---\ntype: "project"\nvisibility: "public"\nsource: "github"\n'
        'external_key: "o/r"\n---\n\n# o-r\n\n## Contributors\n\n- [[People/alice]]\n'
    )


def test_entity_without_edges_gets_note_with_empty_section():
    out = render_vault([_person("solo")], [])
    assert "[[" not in out["People/solo.md"]
    assert "## Projects" in out["People/solo.md"]


def test_empty_input():
    assert render_vault([], []) == {}


@pytest.mark.parametrize("seed", range(5))
def test_output_independent_of_input_order(seed):
    rng = random.Random(seed)
    ents = [_person(f"u{i}") for i in range(4)] + [_project(f"o/p{i}") for i in range(4)]
    edges = [_edge(f"u{i}", f"o/p{j}") for i in range(4) for j in range(i % 3 + 1)]
    expected = render_vault(ents, edges)
    rng.shuffle(ents)
    rng.shuffle(edges)
    assert render_vault(ents, edges) == expected
    assert list(render_vault(ents, edges)) == list(expected)


def test_duplicate_edges_deduplicated_and_links_sorted():
    ents = [_person("a"), _project("o/z"), _project("o/b")]
    edges = [_edge("a", "o/z"), _edge("a", "o/b"), _edge("a", "o/z")]
    body = render_vault(ents, edges)["People/a.md"]
    assert body.count("[[Projects/o-z]]") == 1
    assert body.index("o-b") < body.index("o-z")


def test_every_wikilink_resolves_to_an_output_file():
    ents = [_person("a"), _person("b"), _project("o/x"), _project("o/y")]
    edges = [_edge("a", "o/x"), _edge("b", "o/x"), _edge("b", "o/y")]
    out = render_vault(ents, edges)
    import re

    for content in out.values():
        for link in re.findall(r"\[\[([^\]]+)\]\]", content):
            assert f"{link}.md" in out


def test_unknown_relationship_type_ignored():
    out = render_vault([_person("a"), _project("o/x")], [_edge("a", "o/x", rtype="follows")])
    assert "[[" not in out["People/a.md"] + out["Projects/o-x.md"]


def test_wrong_direction_edge_ignored():
    out = render_vault(
        [_person("a"), _project("o/x")],
        [Relationship("o/x", "project", "a", "person", "contributed_to", "public")],
    )
    assert "[[" not in out["People/a.md"] + out["Projects/o-x.md"]


def test_edge_with_unexported_endpoint_dropped_without_leaking_key():
    out = render_vault([_person("a")], [_edge("a", "secret/repo")])
    assert "secret" not in out["People/a.md"]


def test_unknown_entity_type_skipped_not_rendered():
    out = render_vault([_person("a"), Entity("1", "team", "t", "public")], [])
    assert list(out) == ["People/a.md"]


@pytest.mark.parametrize("vis", ["private", "PRIVATE", "Public", "", None, "internal"])
def test_non_public_entity_rejected_without_echoing_key(vis):
    with pytest.raises(ValueError) as exc:
        render_vault([Entity("1", "person", "topsecret", vis)], [])
    assert "topsecret" not in str(exc.value)


def test_mixed_batch_fails_closed():
    ents = [_person(f"u{i}") for i in range(20)] + [Entity("x", "person", "p", "private")]
    with pytest.raises(ValueError):
        render_vault(ents, [])


def test_collision_gets_stable_hash_suffix_and_does_not_abort():
    files = render_vault([_project("owner/repo"), _project("owner-repo")], [])
    assert len(files) == 2
    assert all(re.fullmatch(r"Projects/owner-repo-[0-9a-f]{8}\.md", f) for f in files)
    assert files == render_vault([_project("owner-repo"), _project("owner/repo")], [])


def test_non_public_relationship_is_refused():
    rel = Relationship("p", "person", "r", "project", "contributed_to", "private")
    with pytest.raises(ValueError, match="non-public relationship"):
        render_vault([_person("p"), _project("r")], [rel])


def test_person_and_project_same_name_do_not_collide():
    assert len(render_vault([_person("x"), _project("x")], [])) == 2


@pytest.mark.parametrize(
    "key,expected",
    [("owner/repo", "owner-repo"), ("a/b/c", "a-b-c"), ("user_name-1", "user_name-1"),
     ("org/my.repo", "org-myrepo"), ("../x", "x"), ("..\\win", "win"), ("a\x00b", "ab"), ("a\nb", "ab")],
)
def test_sanitize_table(key, expected):
    assert r._sanitize_key(key) == expected


@pytest.mark.parametrize("key", ["", "///", "...", "!!!", "../..", "--"])
def test_sanitize_empty_result_falls_back_to_stable_hash_name(key):
    name = r._sanitize_key(key)
    assert re.fullmatch(r"key-[0-9a-f]{8}", name)
    assert name == r._sanitize_key(key)


def test_case_only_collision_gets_hash_suffix():
    files = render_vault([_project("Foo"), _project("foo")], [])
    assert len(files) == 2
    assert len({f.lower() for f in files}) == 2


def test_frontmatter_escapes_unicode_line_separators():
    out = render_vault([_person("a\u2028b")], [])
    assert "\u2028" not in next(iter(out.values())).split("---")[1]


@pytest.mark.parametrize("key", ["../../etc/passwd", "/abs/path", "C:\\x", ".git", "a/../../b", "inject]]x", "o[[l", "p|q"])
def test_hostile_keys_yield_single_safe_path_segment_and_valid_wikilinks(key):
    out = render_vault([_person("a"), _project(key)], [_edge("a", key)])
    for path in out:
        d, name = path.split("/")
        assert d in ("People", "Projects") and name.endswith(".md")
        assert not name.startswith(".") and ".." not in name
    link = [ln for ln in out["People/a.md"].splitlines() if ln.startswith("- [[")][0]
    assert link.count("[[") == 1 and link.count("]]") == 1 and "|" not in link


def test_very_long_key_is_capped_or_rejected():
    try:
        out = render_vault([_person("a" * 5000)], [])
    except ValueError:
        return
    assert all(len(p.split("/")[1]) <= 255 for p in out)


@pytest.mark.parametrize("key", ["k:v", "a #b", '"q"', "'s'", "---", "-x", "key\nnewline", "unicode-测试", "k: v"])
def test_frontmatter_round_trips_key_and_has_exactly_four_fields(key):
    try:
        out = render_vault([_person(key)], [])
    except ValueError:
        return
    fm = _frontmatter(next(iter(out.values())))
    assert fm == {"type": "person", "visibility": "public", "source": "github", "external_key": key}


def test_entities_and_relationships_are_frozen():
    with pytest.raises(Exception):
        _person("a").external_key = "b"  # type: ignore[misc]
    with pytest.raises(Exception):
        _edge("a", "b").relationship_type = "x"  # type: ignore[misc]
