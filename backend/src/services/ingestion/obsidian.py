"""Obsidian vault ingestion runner.

Fetches all .md blobs from OBSIDIAN_GITHUB_REPO via the GitHub API,
skips files whose blob SHA matches the stored record, and upserts
changed/new files into ingested_obsidian_notes.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian import IngestedObsidianNote
from ...models.user import User
from .. import event_bus
from ..obsidian_client import fetch_blob, fetch_tree, vault_repo
from .runner import IngestionError

# ── Frontmatter + metadata helpers ────────────────────────────────


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from body. Returns (fm_dict, body_text).
    No PyYAML dependency — uses regex for the keys Obsidian actually emits.
    """
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    block = content[3:end]
    body = content[end + 4 :].lstrip("\n")
    fm: dict[str, Any] = {}
    for line in block.splitlines():
        m = re.match(r"^([\w-]+):\s*(.*)", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        # YAML list shorthand: tags: [a, b]
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            fm[key] = [
                v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()
            ]
        else:
            fm[key] = val
    return fm, body


def _extract_tags(fm: dict[str, Any], body: str) -> list[str]:
    raw = fm.get("tags", [])
    if isinstance(raw, str):
        raw = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
    tags = [str(t).lstrip("#") for t in (raw if isinstance(raw, list) else [])]
    # Also pick up inline #tags from the body
    inline = re.findall(r"(?<!\w)#([\w/-]+)", body)
    seen = set(tags)
    for t in inline:
        if t not in seen:
            tags.append(t)
            seen.add(t)
    return tags


def _extract_title(fm: dict[str, Any], body: str, path: str) -> str:
    if fm.get("title"):
        return str(fm["title"])
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return PurePosixPath(path).stem


def _word_count(text: str) -> int:
    return len(text.split())


# ── Ingestion entry point ──────────────────────────────────────────


async def ingest(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    repo = vault_repo()

    tree = await fetch_tree(db, user, repo)
    if not tree:
        raise IngestionError(f"obsidian_empty_vault: no .md files found in {repo}")

    # Build a map of path → stored blob_sha for fast skip-check
    existing: dict[str, str] = {}
    rows = await db.execute(
        select(IngestedObsidianNote.github_path, IngestedObsidianNote.blob_sha).where(
            IngestedObsidianNote.user_id == user.id
        )
    )
    for github_path, blob_sha in rows:
        existing[github_path] = blob_sha

    now = datetime.now(timezone.utc)
    upserted: list[dict[str, Any]] = []
    skipped = 0

    for item in tree:
        path: str = item["path"]
        sha: str = item.get("sha", "")

        if existing.get(path) == sha:
            skipped += 1
            continue

        content, blob_sha = await fetch_blob(db, user, repo, path)
        fm, body = _parse_frontmatter(content)
        title = _extract_title(fm, body, path)
        tags = _extract_tags(fm, body)

        upserted.append(
            {
                "user_id": user.id,
                "github_path": path,
                "title": title,
                "content": content,
                "frontmatter": fm,
                "tags": tags,
                "word_count": _word_count(body),
                "blob_sha": blob_sha or sha,
                "last_modified_at": now,
                "ingested_at": now,
            }
        )

    if upserted:
        stmt = pg_insert(IngestedObsidianNote).values(upserted)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "github_path"],
            set_={
                "title": stmt.excluded.title,
                "content": stmt.excluded.content,
                "frontmatter": stmt.excluded.frontmatter,
                "tags": stmt.excluded.tags,
                "word_count": stmt.excluded.word_count,
                "blob_sha": stmt.excluded.blob_sha,
                "last_modified_at": stmt.excluded.last_modified_at,
                "ingested_at": stmt.excluded.ingested_at,
            },
        )
        await db.execute(stmt)
        await db.commit()

    await event_bus.publish(
        "events.obsidian.ingested",
        {
            "user_id": str(user.id),
            "total": len(tree),
            "updated": len(upserted),
            "skipped": skipped,
            "repo": repo,
        },
    )
    return {"total": len(tree), "updated": len(upserted), "skipped": skipped}
