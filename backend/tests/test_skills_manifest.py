"""The bundled skills manifest is what production seeds skill_registry from."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from scripts.register_skills import build_manifest
from scripts.seed_from_mock import SKILLS_MANIFEST, sync_skills_from_manifest
from sqlalchemy.dialects import postgresql


def test_bundled_manifest_has_unique_valid_rows():
    rows = json.loads(SKILLS_MANIFEST.read_text(encoding="utf-8"))
    assert rows
    names = [r["skill_name"] for r in rows]
    assert len(names) == len(set(names))
    for r in rows:
        assert set(r) == {
            "skill_name",
            "display_name",
            "description",
            "source_repo",
            "category",
        }
        assert len(r["skill_name"]) <= 100
        assert len(r["display_name"]) <= 200
        assert r["description"].strip()
        assert 0 < len(r["source_repo"]) <= 100
        assert r["category"] in {"development", "security", "data", "other"}


def test_build_manifest_reads_top_level_skills_only(tmp_path: Path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "SKILL.md").write_text(
        "# Alpha Skill\n\nDoes alpha things.\n"
    )
    (tmp_path / "empty").mkdir()
    (tmp_path / "alpha" / "nested").mkdir()
    (tmp_path / "alpha" / "nested" / "SKILL.md").write_text("# Nested\n\nIgnored.\n")
    registry = tmp_path / "repos.json"
    registry.write_text(
        json.dumps({"repos": {"src": {"components": {"skills": ["alpha"]}}}})
    )

    rows = build_manifest(tmp_path, registry)

    assert rows == [
        {
            "skill_name": "alpha",
            "display_name": "Alpha Skill",
            "description": "Does alpha things.",
            "source_repo": "src",
            "category": "other",
        }
    ]


@pytest.mark.asyncio
async def test_sync_upserts_every_manifest_row():
    session = MagicMock()
    session.execute = AsyncMock()

    count = await sync_skills_from_manifest(session)

    assert count == len(json.loads(SKILLS_MANIFEST.read_text(encoding="utf-8")))
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (skill_name) DO UPDATE" in sql
    for col in ("display_name", "description", "source_repo", "category"):
        assert f"{col} = excluded.{col}" in sql
    assert "updated_at = now()" in sql


@pytest.mark.asyncio
async def test_sync_fails_loudly_when_manifest_missing(tmp_path: Path):
    session = MagicMock()
    session.execute = AsyncMock()

    with pytest.raises(FileNotFoundError):
        await sync_skills_from_manifest(session, tmp_path / "nope.json")
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_rejects_empty_manifest(tmp_path: Path):
    manifest = tmp_path / "skills.json"
    manifest.write_text("[]")
    session = MagicMock()
    session.execute = AsyncMock()

    with pytest.raises(ValueError):
        await sync_skills_from_manifest(session, manifest)
    session.execute.assert_not_awaited()


def test_committed_manifest_matches_skills_directory():
    repo = Path(__file__).resolve().parents[2]
    skills_dir = repo / ".claude" / "skills"
    if not skills_dir.is_dir():
        pytest.skip(".claude/skills not present")
    expected = build_manifest(skills_dir, repo / ".claude" / "github-repos.json")
    assert expected == json.loads(SKILLS_MANIFEST.read_text(encoding="utf-8")), (
        "skills manifest is stale; run register_skills.py --export "
        "(see its module docstring)"
    )


def test_export_flag_writes_manifest(tmp_path: Path, monkeypatch):
    import sys

    from scripts import register_skills

    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "SKILL.md").write_text("# Beta\n\nBeta skill.\n")
    out = tmp_path / "out.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_skills",
            "--skills-dir",
            str(tmp_path),
            "--registry",
            str(tmp_path / "none.json"),
            "--export",
            str(out),
        ],
    )

    register_skills.main()

    assert [r["skill_name"] for r in json.loads(out.read_text())] == ["beta"]
