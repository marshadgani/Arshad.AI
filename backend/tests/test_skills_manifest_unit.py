"""Unit tests for src/skills/manifest.py — load_manifest.

load_manifest is on the container-startup path: it runs before uvicorn
serves its first request. Its contract is therefore "never raises, ever" —
a missing, unreadable, malformed or empty manifest is a "nothing to sync"
condition, not an error. These tests pin that contract for every failure
mode, because a regression here takes down boot rather than just emptying
the Skills tab.

No database: the manifest layer is deliberately pure.

REQ links: NFR-1, NFR-4.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestLoadManifest:
    def test_returns_none_for_missing_file(self, tmp_path, caplog):
        """TC-046: Missing manifest → None (no exception); WARNING logged."""
        from src.skills.manifest import load_manifest

        with caplog.at_level(logging.WARNING, logger="src.skills.manifest"):
            result = load_manifest(tmp_path / "nonexistent.json")
        assert result is None
        assert any("not found" in m for m in caplog.messages)

    def test_returns_none_for_malformed_json(self, tmp_path, caplog):
        """TC-047: Invalid JSON → None (no exception); WARNING logged."""
        from src.skills.manifest import load_manifest

        bad = tmp_path / "manifest.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="src.skills.manifest"):
            result = load_manifest(bad)
        assert result is None
        assert any("unreadable/invalid" in m for m in caplog.messages)

    def test_returns_none_for_empty_array(self, tmp_path, caplog):
        """TC-048: Empty array [] → None (nothing to sync).

        Critical safety property: if an empty manifest were returned as an
        empty list, sync_from_manifest would treat it as "the disk has zero
        skills" and try to converge the table to nothing.
        """
        from src.skills.manifest import load_manifest

        empty = tmp_path / "manifest.json"
        empty.write_text(json.dumps([]) + "\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="src.skills.manifest"):
            result = load_manifest(empty)
        assert result is None
        assert any("empty or malformed" in m for m in caplog.messages)

    def test_returns_none_for_non_list_json(self, tmp_path, caplog):
        """TC-049: JSON object (not array) → None; WARNING logged."""
        from src.skills.manifest import load_manifest

        bad = tmp_path / "manifest.json"
        bad.write_text(json.dumps({"key": "value"}) + "\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="src.skills.manifest"):
            result = load_manifest(bad)
        assert result is None

    def test_returns_none_when_path_is_a_directory(self, tmp_path, caplog):
        """A directory at the manifest path is not a file → None, not OSError."""
        from src.skills.manifest import load_manifest

        d = tmp_path / "manifest.json"
        d.mkdir()
        with caplog.at_level(logging.WARNING, logger="src.skills.manifest"):
            result = load_manifest(d)
        assert result is None

    def test_returns_list_for_valid_manifest(self, tmp_path):
        """TC-050: Valid JSON array with at least one entry → list returned."""
        from src.skills.manifest import load_manifest

        data = [
            {
                "skill_name": "test__skill",
                "display_name": "Test Skill",
                "description": "A test skill.",
                "source_repo": "test-repo",
                "category": "other",
            }
        ]
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        result = load_manifest(manifest)
        assert result is not None
        assert len(result) == 1
        assert result[0]["skill_name"] == "test__skill"

    def test_uses_default_path_when_no_arg(self, monkeypatch, tmp_path):
        """TC-051: Called without an argument, reads MANIFEST_PATH.

        Resolved at call time, not import time — which is what lets tests
        (and the deploy hook) monkeypatch MANIFEST_PATH at all.
        """
        import src.skills.manifest as manifest_mod

        data = [
            {
                "skill_name": "x",
                "display_name": "X",
                "description": "D",
                "source_repo": "r",
                "category": "other",
            }
        ]
        fake_path = tmp_path / "manifest.json"
        fake_path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", fake_path)
        result = manifest_mod.load_manifest()
        assert result is not None
        assert result[0]["skill_name"] == "x"

    def test_never_raises_on_any_error(self, tmp_path):
        """TC-052: load_manifest must not propagate any exception (startup safety)."""
        from src.skills.manifest import load_manifest

        try:
            result = load_manifest(tmp_path / "does_not_exist.json")
        except Exception as exc:  # pragma: no cover - the assertion is the point
            pytest.fail(f"load_manifest raised unexpectedly: {exc}")
        assert result is None

    def test_default_manifest_path_sits_next_to_the_package(self):
        """MANIFEST_PATH must resolve inside src/skills/, which is what ships
        in the Docker image — not a repo-root path that is absent at runtime."""
        from src.skills.manifest import MANIFEST_PATH

        assert MANIFEST_PATH.name == "manifest.json"
        assert MANIFEST_PATH.parent.name == "skills"

    def test_committed_manifest_is_loadable_and_well_formed(self):
        """The artifact actually committed to the repo must load — otherwise
        every deploy silently syncs zero skills and the Skills tab is empty."""
        from src.skills.manifest import MANIFEST_PATH, load_manifest

        rows = load_manifest(MANIFEST_PATH)
        assert rows, "committed manifest.json is missing, empty or malformed"
        required = {
            "skill_name",
            "display_name",
            "description",
            "source_repo",
            "category",
        }
        for row in rows:
            assert required <= set(row), f"manifest row missing keys: {row}"
            assert row["category"] in {"development", "security", "data", "other"}
            assert len(row["skill_name"]) <= 100
            assert len(row["display_name"]) <= 200

    def test_committed_manifest_skill_names_are_unique(self):
        """skill_name is the ON CONFLICT target — a duplicate would make the
        bulk upsert fail with 'ON CONFLICT DO UPDATE command cannot affect
        row a second time' and abort the whole sync."""
        from src.skills.manifest import MANIFEST_PATH, load_manifest

        rows = load_manifest(MANIFEST_PATH) or []
        names = [r["skill_name"] for r in rows]
        assert len(names) == len(set(names))
