"""Access to the committed skills manifest — location and safe loading.

This module owns the *only* knowledge of where `manifest.json` lives; it sits
next to the artifact it describes, so no caller reconstructs the path by
walking `__file__` upwards.

Pure: no database, no SQLAlchemy, no FastAPI. The manifest itself is
generated at build time by `backend/scripts/register_skills.py` (see that
module's docstring for why a committed artifact — rather than a live read of
`.claude/skills/` — is the only source of truth reachable from inside the
backend container).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MANIFEST_PATH: Path = Path(__file__).with_name("manifest.json")


def load_manifest(path: Path | None = None) -> list[dict[str, Any]] | None:
    """Return the manifest rows, or None if unavailable.

    Never raises. A missing, unreadable, malformed or empty manifest is a
    "nothing to sync" condition, not an error: the skills manifest is a
    convenience artifact and a problem with it must never take down
    container startup (see `src.skills.service.sync_from_manifest`).
    """
    manifest_path = path or MANIFEST_PATH

    if not manifest_path.is_file():
        log.warning("skills manifest not found at %s — skipping sync", manifest_path)
        return None

    try:
        rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("skills manifest unreadable/invalid (%s) — skipping sync", exc)
        return None

    if not isinstance(rows, list) or not rows:
        log.warning("skills manifest is empty or malformed — skipping sync")
        return None

    return rows
