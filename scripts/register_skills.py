#!/usr/bin/env python3
"""Scan .claude/skills/ and upsert every skill into the skill_registry DB table.

Usage:
    python3 scripts/register_skills.py
    python3 scripts/register_skills.py --skills-dir /path/to/.claude/skills --registry /path/to/github-repos.json

Idempotent — safe to run repeatedly. Fails gracefully when the DB is unreachable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

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


def _infer_category(slug: str) -> str:
    parts = set(re.split(r"[-_]", slug.lower()))
    if parts & _SECURITY:
        return "security"
    if parts & _DATA:
        return "data"
    if parts & _DEVELOPMENT:
        return "development"
    return "other"


# ── SKILL.md parsing ──────────────────────────────────────────────────────────


def _parse_skill_md(path: Path) -> tuple[str, str]:
    """Return (display_name, description) from a SKILL.md file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    display_name = ""
    description = ""
    in_frontmatter = False
    frontmatter_done = False
    i = 0

    # Skip YAML frontmatter (--- ... ---)
    if lines and lines[0].strip() == "---":
        in_frontmatter = True
        i = 1
        while i < len(lines):
            if lines[i].strip() == "---":
                frontmatter_done = True
                i += 1
                break
            i += 1
    else:
        frontmatter_done = True

    # Find first # heading
    for j in range(i, len(lines)):
        if lines[j].startswith("# "):
            display_name = lines[j][2:].strip()
            i = j + 1
            break

    # Find first non-empty, non-heading paragraph after the heading
    para_lines: list[str] = []
    for j in range(i, len(lines)):
        line = lines[j].strip()
        if line.startswith("#"):
            if para_lines:
                break
            continue
        if line:
            para_lines.append(line)
        elif para_lines:
            break

    raw_desc = " ".join(para_lines)
    # Strip markdown bold/italic/code
    raw_desc = re.sub(r"\*+([^*]+)\*+", r"\1", raw_desc)
    raw_desc = re.sub(r"`([^`]+)`", r"\1", raw_desc)
    description = raw_desc[:250].strip()

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


# ── DB upsert ─────────────────────────────────────────────────────────────────


async def _sync_skills(skills_dir: Path, registry_path: Path) -> None:
    # Import here so the script doesn't crash if SQLAlchemy isn't installed
    try:
        from sqlalchemy import select, text
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
    except ImportError:
        log.error("SQLAlchemy not installed — cannot sync skills to DB")
        sys.exit(1)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.warning("DATABASE_URL not set — skipping DB sync")
        return

    # Import model (path must be on sys.path — caller sets PYTHONPATH or cwd)
    try:
        from src.models.skill import SkillRegistry
    except ImportError:
        log.error(
            "Cannot import src.models.skill — run from backend/ or set PYTHONPATH"
        )
        sys.exit(1)

    repo_map = _build_repo_map(registry_path)
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    skill_dirs = [
        d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
    ]
    log.info("Found %d skills to sync", len(skill_dirs))

    registered = updated = 0
    async with async_session() as session:
        async with session.begin():
            for skill_dir in sorted(skill_dirs):
                slug = skill_dir.name
                skill_md = skill_dir / "SKILL.md"
                display_name, description = _parse_skill_md(skill_md)
                source_repo = repo_map.get(slug, "unknown")
                category = _infer_category(slug)

                existing = await session.scalar(
                    select(SkillRegistry).where(SkillRegistry.skill_name == slug)
                )
                if existing:
                    existing.display_name = display_name
                    existing.description = description
                    existing.source_repo = source_repo
                    existing.category = category
                    updated += 1
                else:
                    session.add(
                        SkillRegistry(
                            id=uuid.uuid4(),
                            skill_name=slug,
                            display_name=display_name,
                            description=description,
                            source_repo=source_repo,
                            category=category,
                        )
                    )
                    registered += 1

    log.info("Skills sync complete — registered: %d, updated: %d", registered, updated)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync .claude/skills/ → skill_registry DB table"
    )
    parser.add_argument(
        "--skills-dir",
        default=str(Path(__file__).resolve().parent.parent / ".claude" / "skills"),
        help="Path to .claude/skills/ directory",
    )
    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent.parent / ".claude" / "github-repos.json"
        ),
        help="Path to .claude/github-repos.json",
    )
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir)
    registry_path = Path(args.registry)

    if not skills_dir.exists():
        log.error("Skills directory not found: %s", skills_dir)
        sys.exit(1)

    try:
        asyncio.run(_sync_skills(skills_dir, registry_path))
    except Exception as exc:
        log.warning("Skills DB sync failed (non-fatal): %s", exc)


if __name__ == "__main__":
    main()
