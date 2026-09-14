"""Unit tests for scripts/register_skills.py — pure-Python helpers.

Covers: _infer_category (all keyword buckets + precedence),
_parse_skill_md (heading, paragraph, frontmatter, edge cases),
build_manifest (key derivation, deduplication, junk filtering,
determinism), write_manifest (byte-determinism, trailing newline),
_build_repo_map (hit, miss, missing registry), and the path resolution
behind the default --skills-dir argument.

No database and no network: every test operates on a fixture tree in
tmp_path, so these run in every CI stage.

REQ links: FR-1, FR-2, NFR-4, SC-7
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the backend/ tree importable when running outside docker.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(base: Path, repo: str, name: str, content: str) -> Path:
    """Create base/<repo>/<name>/SKILL.md and return its path."""
    d = base / repo / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _infer_category — FR-2
# ---------------------------------------------------------------------------


class TestInferCategory:
    def _infer(self, slug: str) -> str:
        from scripts.register_skills import _infer_category

        return _infer_category(slug)

    def test_security_keyword(self):
        """TC-001: 'security' in slug → category=security."""
        assert self._infer("security-review") == "security"

    def test_audit_keyword(self):
        """TC-002: 'audit' in slug → category=security."""
        assert self._infer("audit-helper") == "security"

    def test_vuln_keyword(self):
        """TC-003: 'vuln' in slug → category=security."""
        assert self._infer("vuln-scanner") == "security"

    def test_pentest_keyword(self):
        assert self._infer("pentest-toolkit") == "security"

    def test_threat_keyword(self):
        assert self._infer("threat-model") == "security"

    def test_code_keyword_returns_development(self):
        """TC-004: 'code' in slug → category=development."""
        assert self._infer("code-linter") == "development"

    def test_tdd_keyword_returns_development(self):
        """TC-005: 'tdd' in slug → category=development."""
        assert self._infer("tdd-workflow") == "development"

    def test_agent_keyword(self):
        assert self._infer("agent-builder") == "development"

    def test_skill_keyword(self):
        assert self._infer("skill-manager") == "development"

    def test_mcp_keyword(self):
        assert self._infer("mcp-server-patterns") == "development"

    def test_debug_keyword(self):
        assert self._infer("debug-trace") == "development"

    def test_review_keyword(self):
        assert self._infer("code-review") == "development"

    def test_data_keyword(self):
        """TC-006: 'data' in slug → category=data."""
        assert self._infer("data-pipeline") == "data"

    def test_etl_keyword(self):
        """TC-007: 'etl' in slug → category=data."""
        assert self._infer("etl-pipeline") == "data"

    def test_sql_keyword(self):
        assert self._infer("sql-optimizer") == "data"

    def test_database_keyword(self):
        assert self._infer("database-inspector") == "data"

    def test_ingest_keyword(self):
        assert self._infer("ingest-runner") == "data"

    def test_analytics_keyword(self):
        assert self._infer("analytics-processor") == "data"

    def test_unknown_slug_returns_other(self):
        """TC-008: No matching keyword → category=other."""
        assert self._infer("brainstorming") == "other"

    def test_empty_slug_returns_other(self):
        assert self._infer("") == "other"

    def test_security_beats_data(self):
        """TC-009: security bucket is checked before data and development."""
        assert self._infer("security-data-audit") == "security"

    def test_security_beats_development(self):
        assert self._infer("security-code-review") == "security"

    def test_data_beats_development(self):
        """data bucket is checked before development."""
        assert self._infer("data-agent") == "data"

    def test_case_insensitive_slug(self):
        """Slugs are lowercased before splitting, so directory casing is irrelevant."""
        assert self._infer("Security-Review") == "security"

    def test_matching_is_whole_token_not_substring(self):
        """'codex' must not match the 'code' keyword — tokens are split on -/_ ."""
        assert self._infer("codex") == "other"


# ---------------------------------------------------------------------------
# _parse_skill_md — FR-2
# ---------------------------------------------------------------------------


class TestParseSkillMd:
    """Tests for the SKILL.md file parser."""

    def _parse(
        self, content: str, tmp_path: Path, skill_dir_name: str = "my-skill"
    ) -> tuple[str, str]:
        from scripts.register_skills import _parse_skill_md

        skill_dir = tmp_path / skill_dir_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return _parse_skill_md(skill_dir / "SKILL.md")

    def test_extracts_h1_as_display_name(self, tmp_path):
        """TC-010: First # heading becomes display_name."""
        name, _ = self._parse("# Deep Research\nSearches the web.", tmp_path)
        assert name == "Deep Research"

    def test_extracts_first_paragraph_as_description(self, tmp_path):
        """TC-011: First prose paragraph becomes description."""
        _, desc = self._parse("# Title\nThis is the description.", tmp_path)
        assert desc == "This is the description."

    def test_skips_yaml_frontmatter(self, tmp_path):
        """TC-012: YAML frontmatter between --- delimiters is ignored."""
        content = "---\nname: skill\n---\n# Real Title\nReal description."
        name, _ = self._parse(content, tmp_path)
        assert name == "Real Title"

    def test_falls_back_to_directory_name_when_no_heading(self, tmp_path):
        """TC-013: No # heading → fallback to parent directory name."""
        name, _ = self._parse(
            "No heading here.", tmp_path, skill_dir_name="fallback-skill"
        )
        assert name == "fallback-skill"

    def test_empty_file_returns_safe_defaults(self, tmp_path):
        """TC-014: Empty SKILL.md never raises; returns sentinel description."""
        name, desc = self._parse("", tmp_path, skill_dir_name="empty-skill")
        assert name == "empty-skill"
        assert desc == "No description."

    def test_description_truncated_to_250_chars(self, tmp_path):
        """TC-015: Description never exceeds 250 characters."""
        _, desc = self._parse(f"# T\n{'A' * 300}", tmp_path)
        assert len(desc) <= 250

    def test_strips_markdown_bold_from_description(self, tmp_path):
        """TC-016: **bold** markers are stripped, text preserved."""
        _, desc = self._parse("# T\n**bold text** here", tmp_path)
        assert "**" not in desc
        assert "bold text" in desc

    def test_strips_inline_code_backticks(self, tmp_path):
        """TC-017: `code` backticks stripped; content preserved."""
        _, desc = self._parse("# T\nUse `run()` to start.", tmp_path)
        assert "`" not in desc
        assert "run()" in desc

    def test_description_stops_at_next_heading(self, tmp_path):
        """TC-018: Text under a subsequent heading is not included."""
        _, desc = self._parse(
            "# T\nFirst para.\n\n## Section\nShould not appear.", tmp_path
        )
        assert "Should not appear" not in desc

    def test_description_skips_leading_heading_lines(self, tmp_path):
        """TC-019: Heading lines before any prose are skipped, not included."""
        _, desc = self._parse("# T\n## Sub\nActual description.", tmp_path)
        assert "Sub" not in desc
        assert "Actual description" in desc

    def test_multiline_paragraph_joined_with_space(self, tmp_path):
        """TC-020: Consecutive non-blank lines form one paragraph."""
        _, desc = self._parse("# T\nLine one.\nLine two.", tmp_path)
        assert desc == "Line one. Line two."

    def test_unclosed_frontmatter_returns_strings_without_raising(self, tmp_path):
        """TC-021: Unclosed frontmatter doesn't crash; treated as no frontmatter."""
        name, desc = self._parse(
            "---\nkey: value\n", tmp_path, skill_dir_name="misparse"
        )
        assert name == "misparse"
        assert isinstance(desc, str)

    def test_invalid_utf8_does_not_raise(self, tmp_path):
        """TC-021b: Undecodable bytes are replaced, not raised (errors='replace')."""
        from scripts.register_skills import _parse_skill_md

        skill_dir = tmp_path / "binary-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_bytes(b"# T\n\xff\xfe not utf-8")
        name, desc = _parse_skill_md(skill_dir / "SKILL.md")
        assert name == "T"
        assert isinstance(desc, str)


# ---------------------------------------------------------------------------
# build_manifest — FR-1, FR-2, key derivation, determinism
# ---------------------------------------------------------------------------


class TestBuildManifest:
    """Tests for the top-level manifest generation function."""

    def test_discovers_skill_files(self, tmp_path):
        """TC-022: All SKILL.md files under skills_dir are discovered."""
        from scripts.register_skills import build_manifest

        _make_skill(
            tmp_path, "superpowers", "brainstorming", "# Brainstorming\nIdeation."
        )
        _make_skill(tmp_path, "superpowers", "debugging", "# Debug\nTrace errors.")
        rows = build_manifest(tmp_path, tmp_path / "missing-registry.json")
        assert len(rows) == 2

    def test_empty_skills_dir_returns_empty_list(self, tmp_path):
        """TC-023: No SKILL.md files → empty list (not an error)."""
        from scripts.register_skills import build_manifest

        rows = build_manifest(tmp_path, tmp_path / "missing-registry.json")
        assert rows == []

    def test_nonexistent_skills_dir_returns_empty_list(self, tmp_path):
        """TC-024: skills_dir that doesn't exist → empty list, no exception."""
        from scripts.register_skills import build_manifest

        rows = build_manifest(tmp_path / "nonexistent", tmp_path / "reg.json")
        assert rows == []

    def test_skill_name_is_path_components_joined_with_double_underscore(
        self, tmp_path
    ):
        """TC-025: skill_name = repo + '__' + leaf when nested one level."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "superpowers", "brainstorming", "# B\nD.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert rows[0]["skill_name"] == "superpowers__brainstorming"

    def test_skill_name_depth3_joined_correctly(self, tmp_path):
        """TC-026: Three path components joined with '__'."""
        from scripts.register_skills import build_manifest

        d = tmp_path / "repo" / "category" / "leaf"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# Leaf\nDesc.", encoding="utf-8")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert rows[0]["skill_name"] == "repo__category__leaf"

    def test_two_skills_in_same_repo_produce_distinct_names(self, tmp_path):
        """TC-027: Two skills under the same repo get distinct skill_name values."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "repo", "skill-a", "# A\nDesc.")
        _make_skill(tmp_path, "repo", "skill-b", "# B\nDesc.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        names = {r["skill_name"] for r in rows}
        assert names == {"repo__skill-a", "repo__skill-b"}

    def test_same_leaf_name_in_different_repos_produces_distinct_names(self, tmp_path):
        """TC-028: skill_name stays unique when leaf names collide across repos.

        This is the whole reason skill_name is the full repo-relative path and
        not the leaf directory: 114+ skills on disk share a basename, and
        skill_name is UNIQUE in the DB.
        """
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "repo-a", "frontend-design", "# FD A\nDesc.")
        _make_skill(tmp_path, "repo-b", "frontend-design", "# FD B\nDesc.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        names = {r["skill_name"] for r in rows}
        assert names == {"repo-a__frontend-design", "repo-b__frontend-design"}

    def test_output_is_sorted_by_skill_name(self, tmp_path):
        """TC-029: Output list is alphabetically sorted by skill_name."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "z-repo", "z-skill", "# Z\nZ.")
        _make_skill(tmp_path, "a-repo", "a-skill", "# A\nA.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        names = [r["skill_name"] for r in rows]
        assert names == sorted(names)

    def test_junk_hidden_dir_is_skipped(self, tmp_path):
        """TC-030: Directories starting with '.' are ignored."""
        from scripts.register_skills import build_manifest

        d = tmp_path / ".hidden" / "skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# H\nH.", encoding="utf-8")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert rows == []

    def test_junk_leading_dash_dir_is_skipped(self, tmp_path):
        """TC-031: Directories starting with '-' are filtered (mangled dir names)."""
        from scripts.register_skills import build_manifest

        d = tmp_path / "-eep-research" / "skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# D\nD.", encoding="utf-8")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert rows == []

    def test_symlinked_skill_md_escaping_skills_dir_is_skipped(self, tmp_path):
        """SEC: a SKILL.md symlinked at a file outside skills_dir is not read.

        `.claude/skills/` is filled by `cp -r` of third-party repos, symlinks
        and all. Reading through one would exfiltrate the target's first
        paragraph (e.g. backend/.env) into the committed manifest and onto the
        Skills tab.
        """
        from scripts.register_skills import build_manifest

        secret = tmp_path / "secret.env"
        secret.write_text("SECRET_KEY=supersecret\n", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        (skills_dir / "repo" / "evil").mkdir(parents=True)
        (skills_dir / "repo" / "evil" / "SKILL.md").symlink_to(secret)
        (skills_dir / "repo" / "good").mkdir(parents=True)
        (skills_dir / "repo" / "good" / "SKILL.md").write_text(
            "# Good\n\nA good skill.", encoding="utf-8"
        )

        rows = build_manifest(skills_dir, tmp_path / "r.json")

        assert [r["skill_name"] for r in rows] == ["repo__good"]
        assert "supersecret" not in json.dumps(rows)

    def test_dangling_symlink_skill_md_is_skipped(self, tmp_path):
        """SEC: an unresolvable SKILL.md symlink is skipped, not crashed on."""
        from scripts.register_skills import build_manifest

        d = tmp_path / "repo" / "broken"
        d.mkdir(parents=True)
        (d / "SKILL.md").symlink_to(tmp_path / "nope")

        assert build_manifest(tmp_path, tmp_path / "r.json") == []

    def test_skill_md_directly_in_skills_dir_is_skipped(self, tmp_path):
        """A SKILL.md with no containing directory has no derivable key."""
        from scripts.register_skills import build_manifest

        (tmp_path / "SKILL.md").write_text("# Root\nD.", encoding="utf-8")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert rows == []

    def test_display_name_truncated_to_200_chars(self, tmp_path):
        """TC-032: display_name exceeding 200 chars is silently truncated."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "r", "s", f"# {'X' * 300}\nDesc.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert len(rows[0]["display_name"]) <= 200

    def test_skill_name_within_varchar100_limit(self, tmp_path):
        """TC-033: skill_name stays within the 100-char DB column limit."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "repo", "skill", "# S\nD.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert all(len(r["skill_name"]) <= 100 for r in rows)

    def test_overlong_skill_name_aborts(self, tmp_path):
        """A key longer than the DB column aborts the build rather than
        emitting a row that would blow up at INSERT time in production."""
        import pytest
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "r" * 60, "s" * 60, "# S\nD.")
        with pytest.raises(SystemExit):
            build_manifest(tmp_path, tmp_path / "r.json")

    def test_source_repo_from_registry_hit(self, tmp_path):
        """TC-034: source_repo populated from github-repos.json when matched."""
        from scripts.register_skills import build_manifest

        reg = {"repos": {"superpowers": {"components": {"skills": ["brainstorming"]}}}}
        reg_path = tmp_path / "github-repos.json"
        reg_path.write_text(json.dumps(reg), encoding="utf-8")
        _make_skill(tmp_path, "nested", "brainstorming", "# B\nD.")
        rows = build_manifest(tmp_path, reg_path)
        assert rows[0]["source_repo"] == "superpowers"

    def test_source_repo_falls_back_to_top_level_dir(self, tmp_path):
        """TC-035: Unregistered skill uses top-level directory as source_repo."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "unknown-repo", "my-skill", "# S\nD.")
        rows = build_manifest(tmp_path, tmp_path / "missing.json")
        assert rows[0]["source_repo"] == "unknown-repo"

    def test_missing_registry_does_not_crash(self, tmp_path):
        """TC-036: Missing github-repos.json → source_repo falls back gracefully."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "repo", "skill", "# S\nD.")
        rows = build_manifest(tmp_path, tmp_path / "nonexistent-registry.json")
        assert len(rows) == 1
        assert rows[0]["source_repo"] == "repo"

    def test_manifest_row_keys_are_correct(self, tmp_path):
        """TC-037: Every row has exactly the five required SkillManifestRow keys."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "r", "s", "# S\nD.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert len(rows) == 1
        assert set(rows[0].keys()) == {
            "skill_name",
            "display_name",
            "description",
            "source_repo",
            "category",
        }

    def test_category_is_valid_value(self, tmp_path):
        """TC-038: category field is one of the four legal values."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "r", "brainstorming", "# B\nD.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert rows[0]["category"] in {"development", "security", "data", "other"}

    def test_category_inferred_from_leaf_not_repo(self, tmp_path):
        """Nested skills take their category from their own folder name."""
        from scripts.register_skills import build_manifest

        _make_skill(tmp_path, "brainstorming", "security-review", "# S\nD.")
        rows = build_manifest(tmp_path, tmp_path / "r.json")
        assert rows[0]["category"] == "security"


# ---------------------------------------------------------------------------
# _build_repo_map
# ---------------------------------------------------------------------------


class TestBuildRepoMap:
    def test_missing_registry_returns_empty_map(self, tmp_path):
        from scripts.register_skills import _build_repo_map

        assert _build_repo_map(tmp_path / "nope.json") == {}

    def test_maps_every_listed_skill_to_its_repo(self, tmp_path):
        from scripts.register_skills import _build_repo_map

        reg = {
            "repos": {
                "superpowers": {
                    "components": {"skills": ["brainstorming", "debugging"]}
                },
                "context7": {"components": {"skills": ["find-docs"]}},
            }
        }
        p = tmp_path / "github-repos.json"
        p.write_text(json.dumps(reg), encoding="utf-8")
        assert _build_repo_map(p) == {
            "brainstorming": "superpowers",
            "debugging": "superpowers",
            "find-docs": "context7",
        }

    def test_registry_without_repos_key_returns_empty_map(self, tmp_path):
        from scripts.register_skills import _build_repo_map

        p = tmp_path / "github-repos.json"
        p.write_text(json.dumps({"other": 1}), encoding="utf-8")
        assert _build_repo_map(p) == {}


# ---------------------------------------------------------------------------
# write_manifest — determinism, byte-identical output, trailing newline
# ---------------------------------------------------------------------------


class TestWriteManifest:
    def _rows(self):
        from scripts.register_skills import SkillManifestRow

        return [
            SkillManifestRow(
                skill_name="repo__skill-a",
                display_name="Skill A",
                description="Does A.",
                source_repo="repo",
                category="development",
            ),
            SkillManifestRow(
                skill_name="repo__skill-b",
                display_name="Skill B",
                description="Does B.",
                source_repo="repo",
                category="other",
            ),
        ]

    def test_output_is_valid_json(self, tmp_path):
        """TC-039: Output file parses as JSON without error."""
        from scripts.register_skills import write_manifest

        out = tmp_path / "manifest.json"
        write_manifest(self._rows(), out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 2

    def test_trailing_newline(self, tmp_path):
        """TC-040: File ends with a trailing newline (clean `git diff`)."""
        from scripts.register_skills import write_manifest

        out = tmp_path / "manifest.json"
        write_manifest(self._rows(), out)
        assert out.read_bytes().endswith(b"\n")

    def test_deterministic_byte_identical_output(self, tmp_path):
        """TC-041: Two runs with identical inputs produce byte-identical output."""
        from scripts.register_skills import write_manifest

        out1 = tmp_path / "m1.json"
        out2 = tmp_path / "m2.json"
        write_manifest(self._rows(), out1)
        write_manifest(self._rows(), out2)
        assert out1.read_bytes() == out2.read_bytes()

    def test_key_order_is_fixed(self, tmp_path):
        """TC-042: Each JSON object has keys in the documented order."""
        from scripts.register_skills import write_manifest

        out = tmp_path / "manifest.json"
        write_manifest(self._rows(), out)
        for row in json.loads(out.read_text(encoding="utf-8")):
            assert list(row.keys()) == [
                "skill_name",
                "display_name",
                "description",
                "source_repo",
                "category",
            ]

    def test_creates_parent_directories(self, tmp_path):
        """TC-043: Parent directory is created if it doesn't exist."""
        from scripts.register_skills import write_manifest

        out = tmp_path / "new_dir" / "subdir" / "manifest.json"
        write_manifest(self._rows(), out)
        assert out.exists()

    def test_empty_rows_produces_empty_array(self, tmp_path):
        """TC-044: Zero rows → valid empty JSON array with trailing newline."""
        from scripts.register_skills import write_manifest

        out = tmp_path / "manifest.json"
        write_manifest([], out)
        assert json.loads(out.read_text(encoding="utf-8")) == []
        assert out.read_bytes().endswith(b"\n")

    def test_non_ascii_written_verbatim(self, tmp_path):
        """ensure_ascii=False — an em dash stays an em dash, not \\u2014."""
        from scripts.register_skills import SkillManifestRow, write_manifest

        out = tmp_path / "manifest.json"
        write_manifest(
            [
                SkillManifestRow(
                    skill_name="r__s",
                    display_name="Skill — dashed",
                    description="D.",
                    source_repo="r",
                    category="other",
                )
            ],
            out,
        )
        assert "—" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Default --skills-dir path resolution — FR-1, path-fix regression guard
# ---------------------------------------------------------------------------


class TestDefaultSkillsDir:
    def test_default_skills_dir_resolves_to_repo_root_claude_skills(self):
        """TC-045: The default --skills-dir must land on the real .claude/skills.

        Regression guard for the original path bug (parents[1] instead of
        parents[2]). register_skills.py lives at
        <repo>/backend/scripts/register_skills.py, so parents[2] is <repo>.
        A wrong index silently produces an empty manifest — and an empty
        Skills tab — with exit code 0.
        """
        script_path = (
            Path(__file__).resolve().parents[1] / "scripts" / "register_skills.py"
        )
        assert script_path.exists(), f"register_skills.py not found at {script_path}"
        expected_skills_dir = script_path.parents[2] / ".claude" / "skills"
        assert expected_skills_dir.is_dir(), (
            f"Default skills dir {expected_skills_dir} does not exist — "
            "path resolution bug still present"
        )
