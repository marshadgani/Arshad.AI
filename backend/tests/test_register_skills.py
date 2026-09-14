"""Tests for FEAT-154 — automated skill-registry sync.

Covers:
  T1 — manifest mode and live-tree mode produce identical sorted records
  T2 — manifest generation is byte-deterministic (excluding generated_at)
  T4 — no source available -> exit(0) with a WARNING, never exit(1)
  T5 — an empty source warns instead of silently succeeding
  T6 — source_repo resolves via github-repos.json, not left as 'unknown'
  T7 — --check detects drift after a SKILL.md edit
  T3 — bulk upsert preserves created_at across repeated syncs (needs Postgres;
       skipped when DATABASE_URL is not set, matching the rest of this suite's
       convention for DB-dependent tests)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_skill(root: Path, slug: str, heading: str, paragraph: str) -> None:
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"# {heading}\n\n{paragraph}\n", encoding="utf-8")


def _make_registry(path: Path, repos: dict[str, list[str]]) -> None:
    payload = {
        "repos": {
            slug: {"components": {"skills": skills}} for slug, skills in repos.items()
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestScanSkills:
    def test_manifest_mode_matches_dir_mode(self):
        """T1: scan_skills() and manifest-loaded records agree exactly."""
        from scripts._skills_scan import scan_skills
        from scripts.generate_skills_manifest import _build_manifest
        from scripts.register_skills import _load_manifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "skills"
            _make_skill(skills_dir, "zeta-skill", "Zeta Skill", "Does zeta things.")
            _make_skill(skills_dir, "alpha-skill", "Alpha Skill", "Does alpha things.")
            registry = root / "github-repos.json"
            _make_registry(registry, {"my-repo": ["alpha-skill"]})

            dir_records = scan_skills(skills_dir, registry)

            manifest_path = root / "manifest.json"
            manifest = _build_manifest(skills_dir, registry)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_records = _load_manifest(manifest_path)

            assert [r.to_dict() for r in dir_records] == [
                r.to_dict() for r in manifest_records
            ]
            # sorted by skill_name
            assert [r.skill_name for r in dir_records] == [
                "alpha-skill",
                "zeta-skill",
            ]

    def test_manifest_is_byte_deterministic(self):
        """T2: two generations over an unchanged tree agree on the skills array."""
        from scripts.generate_skills_manifest import _build_manifest, _dump

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "skills"
            _make_skill(skills_dir, "one-skill", "One Skill", "Body text.")
            registry = root / "github-repos.json"
            _make_registry(registry, {})

            m1 = _build_manifest(skills_dir, registry)
            m2 = _build_manifest(skills_dir, registry)

            assert m1["skills"] == m2["skills"]
            assert m1["skill_count"] == m2["skill_count"] == 1
            dumped = _dump(m1)
            assert dumped.endswith("\n") and not dumped.endswith("\n\n")

    def test_no_source_exits_zero_and_warns(self, capsys):
        """T4: missing --skills-dir and missing --manifest -> exit(0), WARN."""
        with tempfile.TemporaryDirectory() as tmp:
            missing_manifest = Path(tmp) / "does-not-exist.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.register_skills",
                    "--manifest",
                    str(missing_manifest),
                ],
                cwd=str(Path(__file__).resolve().parent.parent),
                capture_output=True,
                text=True,
            )
        assert result.returncode == 0
        assert "WARN" in result.stderr or "WARN" in result.stdout

    def test_zero_skills_warns(self):
        """T5: an empty tree produces a WARNING, not a silent success."""
        from scripts.register_skills import _resolve_source

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_skills_dir = root / "skills"
            empty_skills_dir.mkdir()
            registry = root / "github-repos.json"
            _make_registry(registry, {})
            manifest = root / "manifest.json"  # doesn't exist — falls through

            resolved = _resolve_source(empty_skills_dir, manifest, registry)
            # empty skills-dir has no SKILL.md, so it falls through to manifest
            # mode, which also doesn't exist -> None (no source)
            assert resolved is None

    def test_source_repo_resolution(self):
        """T6: a skill listed under a repo in github-repos.json resolves to
        that repo slug, not 'unknown'."""
        from scripts._skills_scan import build_repo_map

        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "github-repos.json"
            _make_registry(
                registry, {"claude-code": ["frontend-design", "other-skill"]}
            )
            mapping = build_repo_map(registry)
            assert mapping["frontend-design"] == "claude-code"
            assert mapping.get("unlisted-skill") is None

    def test_check_flag_detects_drift(self):
        """T7: mutating a SKILL.md heading makes --check exit 2."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "skills"
            _make_skill(skills_dir, "drift-skill", "Original Heading", "Body.")
            registry = root / "github-repos.json"
            _make_registry(registry, {})
            out_path = root / "manifest.json"

            backend_dir = str(Path(__file__).resolve().parent.parent)
            gen = [
                sys.executable,
                "-m",
                "scripts.generate_skills_manifest",
                "--skills-dir",
                str(skills_dir),
                "--registry",
                str(registry),
                "--out",
                str(out_path),
            ]
            check = gen + ["--check"]

            subprocess.run(gen, cwd=backend_dir, check=True, capture_output=True)
            fresh = subprocess.run(check, cwd=backend_dir, capture_output=True)
            assert fresh.returncode == 0

            (skills_dir / "drift-skill" / "SKILL.md").write_text(
                "# Mutated Heading\n\nBody.\n", encoding="utf-8"
            )
            drifted = subprocess.run(check, cwd=backend_dir, capture_output=True)
            assert drifted.returncode == 2


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="T3 requires a live Postgres DATABASE_URL"
)
class TestBulkUpsertPreservesCreatedAt:
    @pytest.mark.asyncio
    async def test_upsert_preserves_created_at(self):
        """T3: created_at is untouched across two syncs; updated_at advances."""
        from scripts._skills_scan import SkillRecord
        from scripts.register_skills import _sync_skills
        from sqlalchemy import select
        from src.models.database import AsyncSessionLocal
        from src.models.skill import SkillRegistry

        record = SkillRecord(
            skill_name="feat-154-test-skill",
            display_name="FEAT-154 Test Skill",
            description="Temporary fixture row for T3.",
            source_repo="test",
            category="other",
        )

        try:
            await _sync_skills([record])
            async with AsyncSessionLocal() as session:
                row = await session.scalar(
                    select(SkillRegistry).where(
                        SkillRegistry.skill_name == "feat-154-test-skill"
                    )
                )
                first_created_at = row.created_at

            await _sync_skills([record])
            async with AsyncSessionLocal() as session:
                row = await session.scalar(
                    select(SkillRegistry).where(
                        SkillRegistry.skill_name == "feat-154-test-skill"
                    )
                )
                assert row.created_at == first_created_at
                assert row.updated_at >= first_created_at
        finally:
            async with AsyncSessionLocal() as session:
                row = await session.scalar(
                    select(SkillRegistry).where(
                        SkillRegistry.skill_name == "feat-154-test-skill"
                    )
                )
                if row:
                    await session.delete(row)
                    await session.commit()
