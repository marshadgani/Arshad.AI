#!/usr/bin/env python3
"""Scan .claude/skills/ and emit a deterministic manifest of every skill found.

This is a pure, DB-free generator. It never talks to Postgres — the manifest
it writes (backend/src/skills/manifest.json by default) is a committed build
artifact that ships inside the backend Docker image and is converged into the
`skill_registry` table at container startup by
`backend/src/skills/service.py::sync_from_manifest`, which is reached from the
Dockerfile CMD / render.yaml preDeployCommand via `scripts/seed_from_mock.py`.

Rationale: `.claude/` lives at the repo root, outside the backend Docker
build context (`dockerContext: ./backend` in render.yaml). No process running
inside the container can read it directly. Generating a manifest at build
time — and committing it — is the only path that reaches the deployed
container without widening the Docker build context.

Usage:
    python3 scripts/register_skills.py
    python3 scripts/register_skills.py --skills-dir /path/to/.claude/skills \\
        --registry /path/to/github-repos.json \\
        --emit-manifest /path/to/backend/src/skills/manifest.json

Deterministic — same input tree always produces byte-identical output, so
`git diff --exit-code` can be used as a CI drift guard.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Literal, TypedDict

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

MAX_SKILL_NAME_LEN = 100
MAX_DISPLAY_NAME_LEN = 200

# Deliberately NOT imported from backend/src/skills/categories.py — this
# script documents itself as dependency-free (see module docstring) so it
# can run outside the backend package/Docker build context. Keep these four
# values in sync with SKILL_CATEGORIES by hand; both are exercised by
# backend/tests/test_ai_ecosystem.py, which would catch drift.
SkillCategory = Literal["development", "security", "data", "other"]


class SkillManifestRow(TypedDict):
    """Shape of one row in the generated manifest.json — and, downstream,
    of one row in the chunk that src/skills/repository.py::bulk_upsert passes
    straight to `pg_insert(SkillRegistry).values(chunk)`. Keeping this
    typed (rather than a bare `dict`) means a future field rename or typo
    here is a type-checker error instead of a silent KeyError — or worse,
    a silently-dropped column — at manifest-sync time in production."""

    skill_name: str
    display_name: str
    description: str
    source_repo: str
    category: SkillCategory


# ── Category inference ────────────────────────────────────────────────────────

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


def _infer_category(slug: str) -> SkillCategory:
    """Infer a coarse category from a skill slug. Signature/body unchanged —
    backend/tests/test_ai_ecosystem.py imports this directly. Return type
    narrowed from `str` to the four-value `SkillCategory` Literal; this is
    an annotation-only change (erased at runtime) so the test import is
    unaffected, but it makes every one of the four `return` statements
    below type-checked against the same enum the DB CHECK constraint and
    RegisterSkillRequest use, instead of an unconstrained `str`."""
    parts = set(re.split(r"[-_]", slug.lower()))
    if parts & _SECURITY:
        return "security"
    if parts & _DATA:
        return "data"
    if parts & _DEVELOPMENT:
        return "development"
    return "other"


# ── SKILL.md parsing ──────────────────────────────────────────────────────────


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


def _parse_skill_md(path: Path) -> tuple[str, str]:
    """Return (display_name, description) from a SKILL.md file. Signature
    unchanged — backend/tests/test_ai_ecosystem.py imports this directly."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body_start = _skip_frontmatter(lines)
    display_name, para_start = _find_heading(lines, body_start)
    description = _extract_paragraph(lines, para_start)
    return display_name or path.parent.name, description or "No description."


# ── Source repo lookup ────────────────────────────────────────────────────────


def _build_repo_map(registry_path: Path) -> dict[str, str]:
    """Return {skill_slug: source_repo_slug} from github-repos.json."""
    if not registry_path.exists():
        return {}
    with open(registry_path) as f:
        reg = json.load(f)
    mapping: dict[str, str] = {}
    for repo_slug, repo_data in reg.get("repos", {}).items():
        for skill_slug in repo_data.get("components", {}).get("skills", []):
            mapping[skill_slug] = repo_slug
    return mapping


# ── Manifest generation ────────────────────────────────────────────────────────


def _is_junk(dir_parts: tuple[str, ...]) -> bool:
    """Skip corrupted/hidden trees (e.g. the mangled `-eep--esearch-skills`
    directory) so they never reach the manifest."""
    return any(p.startswith(".") or p.startswith("-") for p in dir_parts)


def _escapes_skills_dir(skill_md: Path, skills_dir: Path) -> bool:
    """True if `skill_md` (or any directory on the way to it) is a symlink that
    resolves outside `skills_dir`.

    `.claude/skills/` is populated by `scripts/fetch-github-repo.sh`, which
    `cp -r`s whatever a third-party repo ships — symlinks included. A repo
    containing `my-skill/SKILL.md -> /abs/path/backend/.env` would otherwise
    have that file read here, its first paragraph truncated into
    `description`, committed to manifest.json, pushed to GitHub and rendered
    on the Skills tab. Resolve and compare instead of trusting the path.
    """
    try:
        resolved = skill_md.resolve(strict=True)
    except OSError:  # dangling symlink / unreadable
        return True
    return not resolved.is_relative_to(skills_dir.resolve())


def build_manifest(skills_dir: Path, registry_path: Path) -> list[SkillManifestRow]:
    """Discover every SKILL.md under skills_dir at any depth and return a
    sorted, deduplicated list of skill rows. Pure function — no I/O beyond
    reading files under skills_dir and registry_path.

    Key derivation: the skill_name is every directory component between
    skills_dir and SKILL.md, joined with '__' (repo-relative directory path,
    '/' -> '__'). This is required because 114+ skill directories on disk
    share a basename (e.g. two different repos each ship a 'frontend-design'
    skill) and skill_name is UNIQUE in the DB. The leaf directory (the skill's
    own folder) drives category inference; the resolved source repo (via the
    github-repos.json skill->repo map, falling back to the top-level
    directory name) drives source_repo — so both are correct whether a skill
    sits directly under .claude/skills/<name>/ or nested under
    .claude/skills/<repo>/<name>/.
    """
    if not skills_dir.exists():
        return []

    repo_map = _build_repo_map(registry_path)
    rows: dict[str, SkillManifestRow] = {}

    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        rel = skill_md.relative_to(skills_dir)
        dir_parts = rel.parts[:-1]  # exclude "SKILL.md" itself
        if not dir_parts:
            continue
        if _is_junk(dir_parts):
            continue
        if _escapes_skills_dir(skill_md, skills_dir):
            log.warning("skipping symlinked SKILL.md escaping skills dir: %s", rel)
            continue

        skill_name = "__".join(dir_parts)
        if len(skill_name) > MAX_SKILL_NAME_LEN:
            log.error(
                "skill_name exceeds %d chars, aborting: %s",
                MAX_SKILL_NAME_LEN,
                skill_name,
            )
            sys.exit(1)
        if skill_name in rows:
            log.error("duplicate skill_name, aborting: %s", skill_name)
            sys.exit(1)

        leaf = dir_parts[-1]
        display_name, description = _parse_skill_md(skill_md)
        if len(display_name) > MAX_DISPLAY_NAME_LEN:
            display_name = display_name[:MAX_DISPLAY_NAME_LEN]

        if not display_name.strip() and not description.strip():
            continue  # nothing worth showing

        source_repo = repo_map.get(leaf, dir_parts[0])
        category = _infer_category(leaf)

        rows[skill_name] = SkillManifestRow(
            skill_name=skill_name,
            display_name=display_name,
            description=description,
            source_repo=source_repo,
            category=category,
        )

    return [rows[k] for k in sorted(rows)]


def write_manifest(rows: list[SkillManifestRow], out: Path) -> None:
    """Write a deterministic JSON array: sorted rows, fixed key order per row,
    2-space indent, trailing newline — so `git diff --exit-code` is meaningful."""
    ordered = [
        {
            "skill_name": r["skill_name"],
            "display_name": r["display_name"],
            "description": r["description"],
            "source_repo": r["source_repo"],
            "category": r["category"],
        }
        for r in rows
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(
        description="Generate backend/src/skills/manifest.json from .claude/skills/"
    )
    parser.add_argument(
        "--skills-dir",
        default=str(repo_root / ".claude" / "skills"),
        help="Path to .claude/skills/ directory",
    )
    parser.add_argument(
        "--registry",
        default=str(repo_root / ".claude" / "github-repos.json"),
        help="Path to .claude/github-repos.json",
    )
    parser.add_argument(
        "--emit-manifest",
        "--out",
        dest="emit_manifest",
        default=str(repo_root / "backend" / "src" / "skills" / "manifest.json"),
        help="Path to write the generated manifest JSON",
    )
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir)
    registry_path = Path(args.registry)
    out_path = Path(args.emit_manifest)

    if not skills_dir.exists():
        log.error("Skills directory not found: %s", skills_dir)
        sys.exit(1)

    rows = build_manifest(skills_dir, registry_path)
    write_manifest(rows, out_path)
    log.info("Manifest written: %d skills -> %s", len(rows), out_path)


if __name__ == "__main__":
    main()
