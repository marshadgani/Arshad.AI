"""Vault location and export rendering configuration.

Resolving *which* repo is the vault is a configuration question (env var,
per-user Integration override), not an HTTP one — kept out of client.py
so the transport layer never imports the Integration model, and a caller
that only needs the repo name never drags httpx in with it.

``EXPORT_ROOT`` lives here rather than next to the renderers because both
sides of the sync need it: the renderers write under it, and the inbound
ingestor skips anything under it. Neither should have to import the other
to agree on one string.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration import Integration
from ...models.user import User
from ...tools.base import ToolError

# Vault path prefix for all machine-generated notes. The inbound ingestor
# (services/ingestion/obsidian.py) skips any tree entry under this prefix
# so exported notes never re-enter ingested_obsidian_notes.
EXPORT_ROOT = "Arshad.AI/"

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _validated_repo(repo: str, source: str) -> str:
    """Reject anything that isn't a bare 'owner/repo'.

    The value is interpolated straight into GitHub API paths, so a repo
    name carrying '/' segments or '..' must never get that far.
    """
    if not _REPO_RE.match(repo):
        raise ToolError(
            "obsidian_not_configured", f"{source} must be in 'owner/repo' format."
        )
    return repo


@dataclass
class ExportConfig:
    """Rendering configuration — sourced from environment variables via from_env()."""

    snippet_max_chars: int = 500
    include_addresses: bool = False

    @classmethod
    def from_env(cls) -> ExportConfig:
        return cls(
            snippet_max_chars=int(os.getenv("OBSIDIAN_EXPORT_SNIPPET_CHARS", "500")),
            include_addresses=os.getenv(
                "OBSIDIAN_EXPORT_INCLUDE_ADDRESSES", "false"
            ).lower()
            == "true",
        )


def vault_repo() -> str:
    """The globally configured vault repo, as 'owner/repo'."""
    repo = os.getenv("OBSIDIAN_GITHUB_REPO", "").strip()
    if not repo:
        raise ToolError(
            "obsidian_not_configured",
            "OBSIDIAN_GITHUB_REPO is not set. "
            "Set it to your vault GitHub repo, e.g. yourusername/obsidian-vault.",
        )
    return _validated_repo(repo, "OBSIDIAN_GITHUB_REPO")


async def resolve_vault_repo(db: AsyncSession, user: User) -> str:
    """Per-user vault repo override (Integration.config['vault_repo']),
    falling back to the global OBSIDIAN_GITHUB_REPO env var."""
    integration = await db.scalar(
        select(Integration).where(
            Integration.user_id == user.id, Integration.slug == "obsidian"
        )
    )
    if integration and integration.config.get("vault_repo"):
        repo = str(integration.config["vault_repo"]).strip()
        return _validated_repo(repo, "Configured vault_repo")
    return vault_repo()


__all__ = ["EXPORT_ROOT", "ExportConfig", "resolve_vault_repo", "vault_repo"]
