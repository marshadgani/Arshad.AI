"""obsidian_vault_export — renders public ontology entities to markdown and
pushes them to the external vault repo (marshadgani/Arshad-Ideaverse).

Sequence: fetch public entities/relationships -> render (pure) -> git push.
Called from ``runner.run(dag_id="obsidian_vault_export", ...)``, triggered by
``scripts/obsidian_vault_export.py``. No HTTP endpoint.

Scope: GitHub person/project entities only (no calendar/email), write-only
(Arshad.AI never reads the vault back), no Maps of Content, and no
Obsidian Local REST API.

Stale file pruning: when an entity is demoted to private or deleted, its vault
note is removed by the git layer (``git rm --cached``) in the same commit as
new/changed files. This is why ``push_vault`` is always called, even when the
public entity set is empty — the git layer must be given the opportunity to
prune any managed-prefix files that remain in the vault repo.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from . import obsidian_vault_repository as repo
from .errors import IngestionError
from .obsidian_vault_git import push_vault
from .obsidian_vault_render import Entity, Relationship, render_vault

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportSummary:
    status: str
    entities_exported: int
    relationships_exported: int
    files_written: int
    commit_sha: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_entities(rows: list[dict[str, Any]]) -> list[Entity]:
    """Map repository row dicts to ``Entity`` dataclasses."""
    return [
        Entity(
            id=str(r["id"]),
            entity_type=r["entity_type"],
            external_key=r["external_key"],
            visibility=r["visibility"],
        )
        for r in rows
    ]


def _to_relationships(rows: list[dict[str, Any]]) -> list[Relationship]:
    """Map repository row dicts to ``Relationship`` dataclasses."""
    return [
        Relationship(
            source_key=r["source_key"],
            source_type=r["source_type"],
            target_key=r["target_key"],
            target_type=r["target_type"],
            relationship_type=r["relationship_type"],
            visibility=r["visibility"],
        )
        for r in rows
    ]


async def export(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    """Export the user's public ontology to the vault repo and return an ExportSummary dict.

    Never deletes by itself on an empty result: that needs ``allow_empty_prune``.
    """
    entity_rows = await repo.fetch_public_entities(db, user.id)
    rel_rows = await repo.fetch_public_relationships(db, user.id)
    # Reads are done: end the transaction now so no DB connection is held
    # open across the git clone/push (up to minutes). The runner contract
    # requires the module to close its own transaction.
    await db.commit()

    if not entity_rows:
        # An empty set prunes every managed note, so a wrong user id or a bulk
        # demotion bug would wipe the vault with a success status.
        if not payload.get("allow_empty_prune"):
            raise IngestionError(
                "vault_export_refused: no public entities; pass "
                "allow_empty_prune=true in the trigger payload to prune the vault"
            )
        logger.warning("No public entities for user %s; pruning vault by request.", user.id)
    elif not rel_rows:
        logger.warning(
            "No public relationships for user %s: relationships default to "
            "visibility=private (FEAT-165 ratchet); entity notes will have "
            "empty link sections.",
            user.id,
        )

    entities = _to_entities(entity_rows)
    relationships = _to_relationships(rel_rows)

    try:
        files = render_vault(entities, relationships)
    except ValueError as exc:
        raise IngestionError(f"vault_render_failed: {exc}") from exc

    commit_message = (
        f"vault export: {len(files)} notes, {len(relationships)} "
        f"relationships ({datetime.now(timezone.utc).isoformat()})"
    )
    result = await push_vault(files, commit_message)

    return ExportSummary(
        status=result.status,
        entities_exported=len(files),
        relationships_exported=len(relationships),
        files_written=result.files_written,
        commit_sha=result.commit_sha,
    ).as_dict()
