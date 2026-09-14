"""Regression tests for the .claude/skills/ directory scan.

These cover the bug that made Part A a no-op: register_skills.py scanned
with a single-level ``iterdir()``, so every vendored pack laid out as
``<source-repo>/<skill>/SKILL.md`` — including all of obsidian-skills —
was invisible and zero rows reached skill_registry.

Pure filesystem + tmp_path only: no DB, no network. The repo has no DB
test fixtures, and a scan test does not need them — the scan is the part
that was broken.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.register_skills import (
    _collect_skill_dirs,
    _default_skills_root,
    _infer_category,
)

# The six skills synced from kepano/obsidian-skills, nested at
# .claude/skills/obsidian-skills/<skill>/SKILL.md
OBSIDIAN_SKILLS = {
    "defuddle",
    "json-canvas",
    "knap",
    "obsidian-bases",
    "obsidian-cli",
    "obsidian-markdown",
}


def _make_skill(root: Path, *parts: str) -> Path:
    """Create <root>/<parts...>/SKILL.md and return the skill directory."""
    skill_dir = root.joinpath(*parts)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"# {parts[-1].replace('-', ' ').title()}\n\nA skill.\n"
    )
    return skill_dir


class TestCollectSkillDirs:
    def test_nested_pack_skills_are_discovered(self, tmp_path: Path):
        """<source-repo>/<skill>/SKILL.md — the layout iterdir() missed."""
        for skill in ("defuddle", "json-canvas", "obsidian-bases"):
            _make_skill(tmp_path, "obsidian-skills", skill)

        found = {d.name for d in _collect_skill_dirs(tmp_path)}

        assert found == {"defuddle", "json-canvas", "obsidian-bases"}

    def test_top_level_skills_still_discovered(self, tmp_path: Path):
        """The original single-level layout must keep working."""
        _make_skill(tmp_path, "my-skill")

        found = {d.name for d in _collect_skill_dirs(tmp_path)}

        assert found == {"my-skill"}

    def test_both_layouts_discovered_together(self, tmp_path: Path):
        _make_skill(tmp_path, "top-level-skill")
        _make_skill(tmp_path, "some-pack", "nested-skill")

        found = {d.name for d in _collect_skill_dirs(tmp_path)}

        assert found == {"top-level-skill", "nested-skill"}

    def test_skill_md_in_root_is_not_a_skill(self, tmp_path: Path):
        """A SKILL.md sitting directly in skills_dir is not a skill dir."""
        (tmp_path / "SKILL.md").write_text("# Root\n\nNot a skill.\n")

        assert _collect_skill_dirs(tmp_path) == []

    def test_files_nested_inside_a_skill_are_ignored(self, tmp_path: Path):
        """assets/ and references/ copies must not become registry rows."""
        _make_skill(tmp_path, "pack", "skill-tester")
        _make_skill(tmp_path, "pack", "skill-tester", "assets", "sample-skill")

        found = {d.name for d in _collect_skill_dirs(tmp_path)}

        assert "skill-tester" in found
        assert "sample-skill" not in found

    def test_duplicate_slug_dedupes_shallowest_first(self, tmp_path: Path):
        """A top-level skill wins over a same-named one inside a pack."""
        shallow = _make_skill(tmp_path, "shared-skill")
        _make_skill(tmp_path, "container", "shared-skill")

        matches = [d for d in _collect_skill_dirs(tmp_path) if d.name == "shared-skill"]

        assert matches == [shallow]

    def test_result_is_deterministic(self, tmp_path: Path):
        """Repeated scans return an identical, stably ordered list."""
        _make_skill(tmp_path, "b-skill")
        _make_skill(tmp_path, "a-pack", "a-skill")
        _make_skill(tmp_path, "z-pack", "c-skill")

        assert _collect_skill_dirs(tmp_path) == _collect_skill_dirs(tmp_path)

    def test_empty_tree_returns_empty_list(self, tmp_path: Path):
        assert _collect_skill_dirs(tmp_path) == []


class TestAgainstRealRepo:
    """Scan the checked-in .claude/skills/ tree, not a synthetic fixture."""

    @pytest.fixture
    def skills_dir(self) -> Path:
        skills_dir = _default_skills_root() / "skills"
        if not skills_dir.is_dir():
            pytest.skip(".claude/skills/ not present in this checkout")
        return skills_dir

    def test_default_root_resolves_to_repo_root_not_backend(self):
        """.claude/ lives at the repo root, two levels up from this script.

        The default previously resolved to backend/.claude/skills, which
        does not exist — the script exited 1 before scanning anything.
        """
        claude_dir = _default_skills_root()

        assert (claude_dir / "skills").is_dir(), f"{claude_dir}/skills missing"
        assert claude_dir.name == ".claude"

    def test_all_six_obsidian_skills_are_discovered(self, skills_dir: Path):
        """The Part A acceptance criterion, checked against real files."""
        found = {d.name for d in _collect_skill_dirs(skills_dir)}

        missing = OBSIDIAN_SKILLS - found
        assert not missing, f"obsidian-skills not discovered: {sorted(missing)}"

    def test_obsidian_skills_infer_category_other(self):
        """CLAUDE.md 21 requires category='other' for these six."""
        for slug in OBSIDIAN_SKILLS:
            assert _infer_category(slug) == "other", slug

    def test_nested_scan_is_a_superset_of_the_old_single_level_scan(
        self, skills_dir: Path
    ):
        """Fixing discovery must not drop any previously-found skill."""
        old = {
            d.name
            for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }
        new = {d.name for d in _collect_skill_dirs(skills_dir)}

        assert old <= new, f"regressed, lost: {sorted(old - new)}"
        assert new - old, "nested scan found nothing new — scan is still single-level"
