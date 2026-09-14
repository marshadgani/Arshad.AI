#!/usr/bin/env python3
"""Generate backend/data/skills_manifest.json — the production data source
for register_skills.py.

Byte-deterministic: skills sorted by skill_name, json.dump(indent=2,
ensure_ascii=False), single trailing newline, generated_at placed last so
CI diff guards can compare only the skills array.

Usage:
    python -m scripts.generate_skills_manifest
    python -m scripts.generate_skills_manifest --skills-dir ../.claude/skills \
        --registry ../.claude/github-repos.json
    python -m scripts.generate_skills_manifest --check   # CI drift check

Exit codes:
    0  manifest written (or --check matched)
    1  genuine fault (missing --skills-dir, unreadable --registry, write error)
    2  --check found drift
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._skills_scan import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_REGISTRY,
    DEFAULT_SKILLS_DIR,
    scan_skills,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _build_manifest(skills_dir: Path, registry_path: Path) -> dict:
    records = scan_skills(skills_dir, registry_path)
    return {
        "skill_count": len(records),
        "skills": [r.to_dict() for r in records],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _dump(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate backend/data/skills_manifest.json from .claude/skills/"
    )
    parser.add_argument("--skills-dir", default=str(DEFAULT_SKILLS_DIR))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--out", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare a fresh scan against --out; exit 2 on drift, 0 on match. "
        "Does not write the file.",
    )
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir)
    registry_path = Path(args.registry)
    out_path = Path(args.out)

    try:
        manifest = _build_manifest(skills_dir, registry_path)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)

    if args.check:
        if not out_path.exists():
            log.error("--check: %s does not exist", out_path)
            sys.exit(2)
        try:
            committed = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            log.error("--check: %s is not valid JSON: %s", out_path, exc)
            sys.exit(2)

        fresh_skills = manifest["skills"]
        committed_skills = committed.get("skills", [])
        if fresh_skills != committed_skills:
            log.error(
                "manifest stale — run: cd backend && python -m "
                "scripts.generate_skills_manifest --skills-dir %s --registry %s "
                "and commit backend/data/skills_manifest.json",
                skills_dir,
                registry_path,
            )
            log.error(
                "drift: committed %d skills, fresh scan found %d skills",
                len(committed_skills),
                len(fresh_skills),
            )
            sys.exit(2)
        log.info("manifest is up to date (%d skills)", len(fresh_skills))
        sys.exit(0)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_dump(manifest), encoding="utf-8")
    except OSError as exc:
        log.error("failed to write %s: %s", out_path, exc)
        sys.exit(1)

    log.info("wrote %s (%d skills)", out_path, manifest["skill_count"])


if __name__ == "__main__":
    main()
