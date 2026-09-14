"""Subprocess / CLI tests for scripts/register_skills.py.

These run the script as a child process against a controlled fixture tree
in tmp_path — the same way CI and the skill-sync hook invoke it — so they
also cover argument parsing, exit codes and the "runs with no backend
package importable" claim in the script's docstring.

They verify:
  - happy-path manifest generation
  - byte-identical output on a second run (determinism / CI drift guard)
  - malformed SKILL.md files are skipped without aborting (NFR-4)
  - a missing skills dir exits non-zero rather than writing an empty manifest
  - a stale committed manifest is detectable by a plain file diff

No database required.

REQ links: FR-1, FR-2, NFR-4, SC-7.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "register_skills.py"


def _run(
    skills_dir: Path, out: Path, registry: Path | None = None
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--skills-dir",
        str(skills_dir),
        "--emit-manifest",
        str(out),
    ]
    # A nonexistent registry exercises the source_repo fallback path.
    cmd += ["--registry", str(registry or skills_dir.parent / "missing-registry.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_skill(base: Path, repo: str, name: str, content: str) -> None:
    d = base / repo / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")


class TestCliEmitManifest:
    def test_happy_path_creates_valid_manifest(self, tmp_path):
        """TC-096: 3-skill fixture → exit 0 and a valid JSON manifest."""
        for leaf in ("skill-a", "skill-b", "skill-c"):
            _make_skill(tmp_path, "repo", leaf, f"# {leaf}\nDoes {leaf}.")
        out = tmp_path / "manifest.json"
        result = _run(tmp_path, out)
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text(encoding="utf-8"))
        assert {r["skill_name"] for r in data} == {
            "repo__skill-a",
            "repo__skill-b",
            "repo__skill-c",
        }

    def test_second_run_produces_byte_identical_output(self, tmp_path):
        """TC-097: Two runs on one fixture produce identical bytes (drift guard)."""
        _make_skill(tmp_path, "repo", "skill-a", "# A\nD.")
        _make_skill(tmp_path, "repo", "skill-b", "# B\nD.")
        out1 = tmp_path / "manifest1.json"
        out2 = tmp_path / "manifest2.json"
        assert _run(tmp_path, out1).returncode == 0
        assert _run(tmp_path, out2).returncode == 0
        assert out1.read_bytes() == out2.read_bytes()

    def test_missing_skills_dir_exits_nonzero(self, tmp_path):
        """TC-098: Non-existent --skills-dir → non-zero exit.

        The important half is that it must NOT quietly write an empty
        manifest: that would sync an empty Skills tab over a good one.
        """
        out = tmp_path / "manifest.json"
        result = _run(tmp_path / "nonexistent", out)
        assert result.returncode != 0
        assert not out.exists()

    def test_empty_skills_dir_exits_zero(self, tmp_path):
        """TC-099: Empty dir (no SKILL.md files) → exit 0, empty array manifest."""
        skills_dir = tmp_path / "empty"
        skills_dir.mkdir()
        out = tmp_path / "manifest.json"
        result = _run(skills_dir, out)
        assert result.returncode == 0, result.stderr
        assert json.loads(out.read_text(encoding="utf-8")) == []

    def test_malformed_skill_md_skipped_others_included(self, tmp_path):
        """TC-100: An unparseable SKILL.md never aborts the run."""
        _make_skill(tmp_path, "repo", "good-skill", "# Good\nGood description.")
        _make_skill(tmp_path, "repo", "empty-skill", "")
        (tmp_path / "repo" / "binary-skill").mkdir(parents=True)
        (tmp_path / "repo" / "binary-skill" / "SKILL.md").write_bytes(b"\xff\xfe\x00")
        out = tmp_path / "manifest.json"
        result = _run(tmp_path, out)
        assert result.returncode == 0, result.stderr
        names = {r["skill_name"] for r in json.loads(out.read_text(encoding="utf-8"))}
        assert "repo__good-skill" in names

    def test_duplicate_skill_name_aborts(self, tmp_path):
        """Two skills that would collide on skill_name must abort rather than
        emit a manifest whose bulk upsert fails at deploy time with
        'ON CONFLICT DO UPDATE cannot affect row a second time'."""
        # `a/b__c` and `a__b/c` both flatten to `a__b__c`.
        _make_skill(tmp_path, "a", "b__c", "# One\nD.")
        d = tmp_path / "a__b" / "c"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# Two\nD.", encoding="utf-8")
        result = _run(tmp_path, tmp_path / "manifest.json")
        assert result.returncode != 0
        assert "duplicate skill_name" in (result.stderr + result.stdout)

    def test_stale_manifest_detected_by_diff(self, tmp_path):
        """TC-101: CI drift guard — a stale manifest differs from a fresh one."""
        _make_skill(tmp_path, "repo", "skill-a", "# A\nD.")
        stale = tmp_path / "stale.json"
        fresh = tmp_path / "fresh.json"
        stale.write_text(json.dumps([{"skill_name": "stale"}]) + "\n", encoding="utf-8")
        _run(tmp_path, fresh)
        assert stale.read_bytes() != fresh.read_bytes()

    def test_fresh_manifest_matches_committed_manifest(self, tmp_path):
        """TC-102: Regenerating over an up-to-date manifest yields no diff."""
        _make_skill(tmp_path, "repo", "skill-a", "# A\nD.")
        out = tmp_path / "manifest.json"
        _run(tmp_path, out)
        committed = out.read_bytes()
        _run(tmp_path, out)
        assert out.read_bytes() == committed

    def test_output_log_line_mentions_skill_count(self, tmp_path):
        """TC-103: The completion log reports how many skills were written."""
        _make_skill(tmp_path, "repo", "skill-a", "# A\nD.")
        _make_skill(tmp_path, "repo", "skill-b", "# B\nD.")
        out = tmp_path / "manifest.json"
        result = _run(tmp_path, out)
        assert result.returncode == 0
        assert "Manifest written: 2 skills" in (result.stderr + result.stdout)

    def test_runs_without_the_backend_package_importable(self, tmp_path):
        """The script documents itself as dependency-free so it can run outside
        the backend package / Docker build context. Run it from a foreign cwd
        with an empty PYTHONPATH to prove no `src.*` import crept in."""
        _make_skill(tmp_path, "repo", "skill-a", "# A\nD.")
        out = tmp_path / "manifest.json"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--skills-dir",
                str(tmp_path),
                "--registry",
                str(tmp_path / "missing.json"),
                "--emit-manifest",
                str(out),
            ],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(out.read_text(encoding="utf-8"))


class TestCliAgainstRealSkillsTree:
    def test_regenerating_the_committed_manifest_is_a_no_op(self, tmp_path):
        """The strongest drift guard available without CI: regenerate from the
        repo's real .claude/skills/ and compare against the committed
        backend/src/skills/manifest.json. A diff means someone added or
        changed a skill without regenerating — the Skills tab would ship
        stale."""
        repo_root = BACKEND_ROOT.parent
        skills_dir = repo_root / ".claude" / "skills"
        registry = repo_root / ".claude" / "github-repos.json"
        committed = BACKEND_ROOT / "src" / "skills" / "manifest.json"
        assert skills_dir.is_dir(), f"{skills_dir} missing"
        assert committed.is_file(), f"{committed} missing"

        regenerated = tmp_path / "manifest.json"
        result = _run(skills_dir, regenerated, registry)
        assert result.returncode == 0, result.stderr
        assert regenerated.read_bytes() == committed.read_bytes(), (
            "backend/src/skills/manifest.json is out of date — regenerate it "
            "with `python3 backend/scripts/register_skills.py` and commit"
        )
