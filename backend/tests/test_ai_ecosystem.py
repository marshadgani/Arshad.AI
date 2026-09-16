"""Unit tests for AI Ecosystem — pure-Python helpers and schema validation.

Covers:
  _parse_md          — agent .md file parser (happy path + edge cases)
  _cutoff            — period → datetime helper
  RegisterAgentRequest — Pydantic schema validation
  AgentMetricResponse  — efficiency_score field constraints
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# _parse_md
# ---------------------------------------------------------------------------


class TestParseMd:
    def _md(self, content: str, filename: str = "my-agent.md") -> dict:
        from scripts.register_agent import _parse_md

        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return _parse_md(path)
        finally:
            os.unlink(path)
            os.rmdir(tmpdir)

    def test_extracts_agent_name_from_filename(self):
        result = self._md("# My Agent\nDoes great things.", "code-reviewer.md")
        assert result["agent_name"] == "code-reviewer"

    def test_extracts_display_name_from_h1(self):
        result = self._md("# Code Reviewer\nDoes great things.")
        assert result["display_name"] == "Code Reviewer"

    def test_display_name_falls_back_to_title_case(self):
        result = self._md("No heading here.\nJust text.", "my-agent.md")
        assert result["display_name"] == "My Agent"

    def test_extracts_purpose_from_first_paragraph(self):
        result = self._md("# Title\nThis is the purpose line.\nMore text.")
        assert result["purpose"] == "This is the purpose line."

    def test_purpose_skips_headings(self):
        result = self._md("# Title\n## Subtitle\nActual purpose here.")
        assert result["purpose"] == "Actual purpose here."

    def test_purpose_skips_code_blocks(self):
        result = self._md("```python\ncode here\n```\nPurpose after code.")
        assert result["purpose"] == "Purpose after code."

    def test_purpose_truncated_to_250_chars(self):
        long_line = "A" * 300
        result = self._md(f"# Title\n{long_line}")
        assert len(result["purpose"]) <= 250

    def test_detects_opus_model(self):
        result = self._md("# Agent\nUses Claude Opus for deep reasoning.")
        assert result["model"] == "claude-opus-4-8"

    def test_detects_haiku_model(self):
        result = self._md("# Agent\nUses Haiku for fast responses.")
        assert result["model"] == "claude-haiku-4-5-20251001"

    def test_defaults_to_sonnet(self):
        result = self._md("# Agent\nA general purpose agent.")
        assert result["model"] == "claude-sonnet-4-6"

    def test_opus_takes_precedence_over_haiku(self):
        result = self._md("# Agent\nMentions opus and haiku.")
        assert result["model"] == "claude-opus-4-8"

    def test_file_not_found_raises(self):
        from scripts.register_agent import _parse_md

        with pytest.raises(OSError):
            _parse_md("/nonexistent/path/agent.md")


# ---------------------------------------------------------------------------
# _cutoff
# ---------------------------------------------------------------------------


class TestCutoff:
    def test_cutoff_1h_is_in_the_past(self):
        from src.api.v1.ai_ecosystem import _cutoff

        result = _cutoff("1h")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        diff = datetime.now(timezone.utc) - result
        assert 3590 < diff.total_seconds() < 3610

    def test_cutoff_1d(self):
        from src.api.v1.ai_ecosystem import _cutoff

        diff = datetime.now(timezone.utc) - _cutoff("1d")
        assert 86390 < diff.total_seconds() < 86410

    def test_cutoff_1y(self):
        from src.api.v1.ai_ecosystem import _cutoff

        diff = datetime.now(timezone.utc) - _cutoff("1y")
        assert 364 <= diff.days <= 365


# ---------------------------------------------------------------------------
# RegisterAgentRequest schema
# ---------------------------------------------------------------------------


class TestRegisterAgentRequest:
    def _make(self, **kwargs):
        from src.schemas.ai_ecosystem import RegisterAgentRequest

        defaults = {
            "agent_name": "test-agent",
            "display_name": "Test Agent",
            "purpose": "Runs tests.",
        }
        return RegisterAgentRequest(**(defaults | kwargs))

    def test_valid_request_accepted(self):
        req = self._make()
        assert req.agent_name == "test-agent"
        assert req.category == "other"
        assert req.model == "claude-sonnet-4-6"

    def test_development_team_category_accepted(self):
        req = self._make(category="development_team", pipeline_stage=3)
        assert req.category == "development_team"
        assert req.pipeline_stage == 3

    def test_empty_agent_name_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(agent_name="")

    def test_empty_purpose_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(purpose="")

    def test_invalid_category_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(category="unknown_category")

    def test_pipeline_stage_defaults_to_none(self):
        req = self._make()
        assert req.pipeline_stage is None


# ---------------------------------------------------------------------------
# AgentMetricResponse — efficiency_score bounds
# ---------------------------------------------------------------------------


class TestAgentMetricResponse:
    def _make(self, **kwargs):
        from src.schemas.ai_ecosystem import AgentMetricResponse

        defaults = {
            "agent_name": "code-reviewer",
            "usage_count": 10,
            "total_tokens": 5000,
            "avg_tokens_per_use": 500,
            "success_rate": 0.95,
            "efficiency_score": 80,
        }
        return AgentMetricResponse(**(defaults | kwargs))

    def test_efficiency_score_100_accepted(self):
        r = self._make(efficiency_score=100)
        assert r.efficiency_score == 100

    def test_efficiency_score_0_accepted(self):
        r = self._make(efficiency_score=0)
        assert r.efficiency_score == 0

    def test_efficiency_score_above_100_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(efficiency_score=101)

    def test_efficiency_score_below_0_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(efficiency_score=-1)


# ---------------------------------------------------------------------------
# RegisterSkillRequest schema
# ---------------------------------------------------------------------------


class TestRegisterSkillRequest:
    def _make(self, **kwargs):
        from src.schemas.ai_ecosystem import RegisterSkillRequest

        defaults = {
            "skill_name": "deep-research",
            "display_name": "Deep Research",
            "description": "Runs multi-source research across the web.",
        }
        return RegisterSkillRequest(**(defaults | kwargs))

    def test_valid_request_accepted(self):
        req = self._make()
        assert req.skill_name == "deep-research"
        assert req.category == "other"
        assert req.source_repo == "unknown"

    def test_empty_skill_name_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(skill_name="")

    def test_empty_description_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(description="")

    def test_description_over_5000_chars_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(description="x" * 5001)

    def test_invalid_category_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(category="unknown_category")

    def test_development_category_accepted(self):
        req = self._make(category="development")
        assert req.category == "development"

    def test_security_category_accepted(self):
        req = self._make(category="security")
        assert req.category == "security"

    def test_data_category_accepted(self):
        req = self._make(category="data")
        assert req.category == "data"


# ---------------------------------------------------------------------------
# _infer_category (register_skills.py)
# ---------------------------------------------------------------------------


class TestInferCategory:
    def _infer(self, slug: str) -> str:
        from scripts.register_skills import _infer_category

        return _infer_category(slug)

    def test_security_keyword_returns_security(self):
        assert self._infer("security-review") == "security"

    def test_audit_keyword_returns_security(self):
        assert self._infer("audit-helper") == "security"

    def test_dev_keyword_returns_development(self):
        assert self._infer("code-linter") == "development"

    def test_test_keyword_returns_development(self):
        assert self._infer("tdd-workflow") == "development"

    def test_data_keyword_returns_data(self):
        assert self._infer("etl-pipeline") == "data"

    def test_sql_keyword_returns_data(self):
        assert self._infer("sql-optimizer") == "data"

    def test_unknown_slug_returns_other(self):
        assert self._infer("brainstorming") == "other"

    def test_security_beats_data(self):
        # slug contains both security and data keywords
        assert self._infer("security-data-audit") == "security"


# ---------------------------------------------------------------------------
# _skip_frontmatter / _find_heading / _extract_paragraph / _parse_skill_md
# ---------------------------------------------------------------------------


class TestParseSkillMd:
    def _parse(self, content: str, filename: str = "my-skill") -> tuple[str, str]:
        import tempfile

        from scripts.register_skills import _parse_skill_md

        with tempfile.TemporaryDirectory() as d:
            skill_dir = Path(d) / filename
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
            return _parse_skill_md(skill_dir / "SKILL.md")

    def test_extracts_h1_as_display_name(self):
        name, _ = self._parse("# Deep Research\nSearches the web.")
        assert name == "Deep Research"

    def test_extracts_first_paragraph_as_description(self):
        _, desc = self._parse("# Title\nThis is the description.")
        assert desc == "This is the description."

    def test_skips_yaml_frontmatter(self):
        content = "---\nname: skill\n---\n# Real Title\nReal description."
        name, _ = self._parse(content)
        assert name == "Real Title"

    def test_falls_back_to_directory_name_when_no_heading(self):
        name, _ = self._parse("No heading here.", filename="my-skill")
        assert name == "my-skill"

    def test_empty_file_returns_safe_defaults(self):
        name, desc = self._parse("", filename="empty-skill")
        assert name == "empty-skill"
        assert desc == "No description."

    def test_description_truncated_to_250_chars(self):
        _, desc = self._parse(f"# T\n{'A' * 300}")
        assert len(desc) <= 250

    def test_strips_markdown_bold(self):
        _, desc = self._parse("# T\n**bold text** here")
        assert "**" not in desc
        assert "bold text" in desc

    def test_description_stops_at_next_heading(self):
        _, desc = self._parse("# T\nFirst para.\n\n## Section\nShould not appear.")
        assert "Should not appear" not in desc
