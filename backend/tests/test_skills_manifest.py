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
        assert r["description"]


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


@pytest.mark.asyncio
async def test_sync_skips_when_manifest_missing(tmp_path: Path):
    session = MagicMock()
    session.execute = AsyncMock()

    assert await sync_skills_from_manifest(session, tmp_path / "nope.json") == 0
    session.execute.assert_not_awaited()
