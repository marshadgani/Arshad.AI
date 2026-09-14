#!/usr/bin/env python3
"""Sync skills into the skill_registry DB table.

Three-tier source resolution (checked in order):
  1. --skills-dir, if given and it exists and contains >=1 */SKILL.md
     (local dev, docker-compose db-init, CI, fetch-github-repo.sh)
  2. --manifest, the committed backend/data/skills_manifest.json
     (production — Render, backend Dockerfile CMD)
  3. neither available -> WARNING on stderr, exit(0). A missing source is
     not a fault; it just means nothing to sync this run.

Usage:
    python -m scripts.register_skills
    python -m scripts.register_skills --skills-dir /app/.claude/skills \
        --registry /app/.claude/github-repos.json
    python -m scripts.register_skills --dry-run

Idempotent — safe to run repeatedly. Exits 1 only for genuine faults
(DB unreachable, malformed manifest, import failure) — never for a
missing/empty source, which is expected in some environments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._skills_scan import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_REGISTRY,
    SkillRecord,
    build_repo_map,
    infer_category,
    parse_skill_md,
    scan_skills,
)

# Re-exported for one release so any out-of-tree caller of the old private
# names keeps working. New code should import from scripts._skills_scan.
_infer_category = infer_category
_parse_skill_md = parse_skill_md
_build_repo_map = build_repo_map

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

STALE_AFTER_DAYS = int(os.getenv("SKILLS_MANIFEST_MAX_AGE_DAYS", "30"))
_UNKNOWN_SOURCE_WARN_RATIO = 0.20


# ── Source resolution ────────────────────────────────────────────────────────


def _has_skill_dirs(skills_dir: Path) -> bool:
    if not skills_dir.is_dir():
        return False
    return any(d.is_dir() and (d / "SKILL.md").exists() for d in skills_dir.iterdir())


def _load_manifest(manifest_path: Path) -> list[SkillRecord]:
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    skills = data.get("skills", [])
    reported_count = data.get("skill_count")
    if reported_count is not None and reported_count != len(skills):
        log.warning(
            "[skill-sync] WARN manifest skill_count (%s) disagrees with "
            "len(skills) (%d) — using actual array length",
            reported_count,
            len(skills),
        )

    generated_at = data.get("generated_at")
    if generated_at:
        try:
            generated = datetime.fromisoformat(generated_at)
            age = datetime.now(timezone.utc) - generated
            if age > timedelta(days=STALE_AFTER_DAYS):
                log.warning(
                    "[skill-sync] WARN manifest is %d days old (generated_at=%s) "
                    "— consider regenerating",
                    age.days,
                    generated_at,
                )
        except ValueError:
            log.warning(
                "[skill-sync] WARN manifest generated_at is not valid ISO 8601: %s",
                generated_at,
            )

    return [
        SkillRecord(
            skill_name=s["skill_name"],
            display_name=s["display_name"],
            description=s["description"],
            source_repo=s.get("source_repo", "unknown"),
            category=s.get("category", "other"),
        )
        for s in skills
    ]


def _resolve_source(
    skills_dir: Path | None, manifest_path: Path, registry_path: Path
) -> tuple[str, list[SkillRecord]] | None:
    """Return (mode, records) or None if no source is available."""
    if skills_dir is not None and _has_skill_dirs(skills_dir):
        records = scan_skills(skills_dir, registry_path)
        log.info(
            "[skill-sync] source=live-tree path=%s skills=%d", skills_dir, len(records)
        )
        return "live-tree", records

    if manifest_path.exists():
        records = _load_manifest(manifest_path)
        log.info(
            "[skill-sync] source=manifest path=%s skills=%d",
            manifest_path,
            len(records),
        )
        return "manifest", records

    log.warning(
        "[skill-sync] WARN skill sync skipped — no source (no --skills-dir, "
        "no manifest at %s)",
        manifest_path,
    )
    return None


def _warn_on_degraded_outcome(mode: str, records: list[SkillRecord]) -> None:
    if not records:
        log.warning("[skill-sync] WARN source '%s' resolved to 0 skills", mode)
        return
    unknown = sum(1 for r in records if r.source_repo == "unknown")
    if unknown / len(records) > _UNKNOWN_SOURCE_WARN_RATIO:
        log.warning(
            "[skill-sync] WARN %d/%d skills (%.0f%%) resolved to "
            "source_repo='unknown' — check --registry path",
            unknown,
            len(records),
            100 * unknown / len(records),
        )


# ── DB upsert ─────────────────────────────────────────────────────────────────


class SkillSyncError(RuntimeError):
    """Configuration or environment fault that prevents the DB sync.

    Raised — never a bare ``sys.exit()`` — so ``_sync_skills`` stays a pure
    coroutine safe to ``await`` from any caller. A ``sys.exit()`` here would
    raise ``SystemExit`` straight through ``asyncio.run()``: fine for the
    CLI entrypoint below (which wants exactly that), but a landmine for any
    future in-process caller (e.g. a FastAPI startup hook) — it would tear
    down the whole host process instead of letting the caller decide how to
    handle a missing DATABASE_URL or a broken import.
    """


async def _sync_skills(records: list[SkillRecord]) -> tuple[int, int, int]:
    """Bulk upsert; returns (registered, updated, removed).

    `records` is always treated as the complete, authoritative set for this
    run (a full live-tree scan or the full manifest) — never a partial
    delta — so any DB row whose skill_name is absent from it corresponds to
    a skill that no longer exists on disk and is deleted. Without this, the
    Skills tab would only ever grow: a skill removed from .claude/skills/
    would keep showing up forever, which defeats the point of syncing at
    all (FEAT-154 — "Skills tab reflects reality").

    Raises `SkillSyncError` for configuration/import faults instead of
    exiting the process (see `SkillSyncError` docstring).
    """
    try:
        from sqlalchemy import delete, func, select
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    except ImportError as exc:
        raise SkillSyncError(
            "SQLAlchemy not installed — cannot sync skills to DB"
        ) from exc

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise SkillSyncError(
            "DATABASE_URL not set — skills DB sync skipped; set DATABASE_URL to enable"
        )

    try:
        from src.models.skill import SkillRegistry
    except ImportError as exc:
        raise SkillSyncError(
            "Cannot import src.models.skill — run from backend/ or set PYTHONPATH"
        ) from exc

    if not records:
        return 0, 0, 0

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with async_session() as session:
            async with session.begin():
                existing_names = set(
                    (await session.scalars(select(SkillRegistry.skill_name))).all()
                )

                rows = [
                    {
                        "id": uuid.uuid4(),
                        "skill_name": r.skill_name,
                        "display_name": r.display_name,
                        "description": r.description,
                        "source_repo": r.source_repo,
                        "category": r.category,
                    }
                    for r in records
                ]

                CHUNK = 500
                for i in range(0, len(rows), CHUNK):
                    chunk = rows[i : i + CHUNK]
                    stmt = pg_insert(SkillRegistry).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["skill_name"],
                        set_={
                            "display_name": stmt.excluded.display_name,
                            "description": stmt.excluded.description,
                            "source_repo": stmt.excluded.source_repo,
                            "category": stmt.excluded.category,
                            # onupdate= does not fire for Core INSERT..ON
                            # CONFLICT — must be set explicitly. created_at
                            # is deliberately absent from set_.
                            "updated_at": func.now(),
                        },
                    )
                    await session.execute(stmt)

                current_names = {r.skill_name for r in records}
                stale_names = existing_names - current_names
                removed = 0
                if stale_names:
                    result = await session.execute(
                        delete(SkillRegistry).where(
                            SkillRegistry.skill_name.in_(stale_names)
                        )
                    )
                    removed = result.rowcount or 0

        registered = sum(1 for r in records if r.skill_name not in existing_names)
        updated = len(records) - registered
        return registered, updated, removed
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync skills -> skill_registry DB table"
    )
    parser.add_argument(
        "--skills-dir",
        default=None,
        help="Path to a live .claude/skills/ directory (dev/CI mode). "
        "If omitted or absent, falls back to --manifest.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to the committed skills_manifest.json (production default source)",
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="Path to .claude/github-repos.json (only used in live-tree mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the source and print counts without touching the DB",
    )
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir) if args.skills_dir else None
    manifest_path = Path(args.manifest)
    registry_path = Path(args.registry)

    try:
        resolved = _resolve_source(skills_dir, manifest_path, registry_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.error("skill sync failed: %s", exc)
        sys.exit(1)

    if resolved is None:
        sys.exit(0)

    mode, records = resolved
    _warn_on_degraded_outcome(mode, records)

    if args.dry_run:
        by_category: dict[str, int] = {}
        for r in records:
            by_category[r.category] = by_category.get(r.category, 0) + 1
        log.info(
            "[skill-sync] dry-run: mode=%s total=%d by_category=%s",
            mode,
            len(records),
            by_category,
        )
        return

    try:
        registered, updated, removed = asyncio.run(_sync_skills(records))
    except SkillSyncError as exc:
        log.error("%s", exc)
        sys.exit(1)
    except Exception as exc:
        log.error("Skills DB sync failed: %s", exc)
        sys.exit(1)

    log.info(
        "Skills sync complete — mode: %s, registered: %d, updated: %d, removed: %d",
        mode,
        registered,
        updated,
        removed,
    )


if __name__ == "__main__":
    main()
