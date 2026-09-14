"""Shared scanning/parsing logic for .claude/skills/ -> skill_registry.

Single source of truth consumed by both:
  - generate_skills_manifest.py  (writes backend/data/skills_manifest.json)
  - register_skills.py           (upserts into the DB, either from a live
                                   tree or from the committed manifest)

Kept dependency-free (stdlib only) so the manifest generator never needs
`pip install -r requirements.txt` in CI.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# backend/scripts/_skills_scan.py -> parents[0]=scripts, [1]=backend, [2]=repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
DEFAULT_REGISTRY = _REPO_ROOT / ".claude" / "github-repos.json"
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parent.parent / "data" / "skills_manifest.json"
)

# ── Category inference ──────────────────────────────────────────────────────

_SECURITY = {"security", "audit", "vuln", "pentest", "threat"}
_DEVELOPMENT = {
    "test",
    "tdd",
    "spec",
    "agent",
    "skill",
    "command",
    "hook",
    "mcp",
    "dev",
    "code",
    "lint",
    "review",
    "debug",
}
_DATA = {"data", "pipeline", "ingest", "etl", "analytics", "db", "database", "sql"}


def infer_category(slug: str) -> str:
    parts = set(re.split(r"[-_]", slug.lower()))
    if parts & _SECURITY:
        return "security"
    if parts & _DATA:
        return "data"
    if parts & _DEVELOPMENT:
        return "development"
    return "other"


# ── SKILL.md parsing ─────────────────────────────────────────────────────────


def _skip_frontmatter(lines: list[str]) -> int:
    """Return index of first line after the closing --- of YAML frontmatter, or 0."""
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    return 0


def _find_heading(lines: list[str], start: int) -> tuple[str, int]:
    """Return (h1_text, next_line_index) for the first # heading at or after start."""
    for i in range(start, len(lines)):
        if lines[i].startswith("# "):
            return lines[i][2:].strip(), i + 1
    return "", start


def _extract_paragraph(lines: list[str], start: int) -> str:
    """Return the first non-empty, non-heading paragraph as a plain string."""
    para_lines: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            if para_lines:
                break
            continue
        if stripped:
            para_lines.append(stripped)
        elif para_lines:
            break
    raw = " ".join(para_lines)
    raw = re.sub(r"\*+([^*]+)\*+", r"\1", raw)
    raw = re.sub(r"`([^`]+)`", r"\1", raw)
    return raw[:250].strip()


def parse_skill_md(path: Path) -> tuple[str, str]:
    """Return (display_name, description) from a SKILL.md file."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body_start = _skip_frontmatter(lines)
    display_name, para_start = _find_heading(lines, body_start)
    description = _extract_paragraph(lines, para_start)
    return display_name or path.parent.name, description or "No description."


# ── Source repo lookup ───────────────────────────────────────────────────────


def build_repo_map(registry_path: Path) -> dict[str, str]:
    """Return {skill_slug: source_repo_slug} from github-repos.json.

    Contract: an explicitly-passed registry path that does not exist is a
    hard error (the caller asked for it by name and it's missing — that's a
    real misconfiguration). The *default* path missing is expected in some
    environments (e.g. a stripped-down container) and degrades to an empty
    map with every skill resolving to source_repo='unknown', not a crash.
    """
    if not registry_path.exists():
        if registry_path == DEFAULT_REGISTRY:
            return {}
        raise FileNotFoundError(f"--registry path does not exist: {registry_path}")
    with open(registry_path, encoding="utf-8") as f:
        reg = json.load(f)
    mapping: dict[str, str] = {}
    for repo_slug, repo_data in reg.get("repos", {}).items():
        for skill_slug in repo_data.get("components", {}).get("skills", []):
            mapping[skill_slug] = repo_slug
    return mapping


# ── Combined scan ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkillRecord:
    skill_name: str
    display_name: str
    description: str
    source_repo: str
    category: str

    def to_dict(self) -> dict[str, str]:
        return {
            "skill_name": self.skill_name,
            "display_name": self.display_name,
            "description": self.description,
            "source_repo": self.source_repo,
            "category": self.category,
        }


def scan_skills(skills_dir: Path, registry_path: Path) -> list[SkillRecord]:
    """Scan depth-1 subdirectories of skills_dir containing SKILL.md.

    Returns records sorted by skill_name (ASCII sort) — this ordering is
    the manifest's determinism contract; callers must not re-sort.
    """
    if not skills_dir.exists():
        raise FileNotFoundError(f"skills directory does not exist: {skills_dir}")

    repo_map = build_repo_map(registry_path)
    skill_dirs = sorted(
        d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
    )

    records: list[SkillRecord] = []
    for skill_dir in skill_dirs:
        slug = skill_dir.name
        display_name, description = parse_skill_md(skill_dir / "SKILL.md")
        records.append(
            SkillRecord(
                skill_name=slug,
                display_name=display_name,
                description=description,
                source_repo=repo_map.get(slug, "unknown"),
                category=infer_category(slug),
            )
        )
    return records
