"""GitHub client for Obsidian vault read/write operations.

Reuses the user's linked GitHub OAuth token (same infrastructure as the
GitHub tools). The vault repo path comes from OBSIDIAN_GITHUB_REPO env var.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any
from urllib.parse import quote as url_quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User
from ..tools.base import ProviderReauthRequired, ToolError
from ..tools.token_service import get_access_token

_BASE = "https://api.github.com"
_TIMEOUT = 20.0
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
logger = logging.getLogger(__name__)


def vault_repo() -> str:
    repo = os.getenv("OBSIDIAN_GITHUB_REPO", "").strip()
    if not repo:
        raise ToolError(
            "obsidian_not_configured",
            "OBSIDIAN_GITHUB_REPO is not set. "
            "Set it to your vault GitHub repo, e.g. yourusername/obsidian-vault.",
        )
    if not _REPO_RE.match(repo):
        raise ToolError(
            "obsidian_not_configured",
            "OBSIDIAN_GITHUB_REPO must be in 'owner/repo' format.",
        )
    return repo


async def _auth_headers(db: AsyncSession, user: User) -> dict[str, str]:
    access_token, _ = await get_access_token(db, user, "github")
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _raise_for_status(resp: httpx.Response, context: str) -> None:
    if resp.status_code == 401:
        raise ProviderReauthRequired("github")
    if resp.status_code == 404:
        raise ToolError("obsidian_not_found", f"{context}: resource not found.")
    if resp.status_code == 403:
        raise ToolError("github_forbidden", f"{context}: access denied.")
    if resp.status_code >= 400:
        raise ToolError(
            "obsidian_api_error",
            f"{context}: GitHub returned {resp.status_code}.",
        )


async def fetch_tree(db: AsyncSession, user: User, repo: str) -> list[dict[str, Any]]:
    """Returns all .md blob entries from the repo's HEAD tree (recursive)."""
    headers = await _auth_headers(db, user)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, base_url=_BASE, headers=headers
    ) as client:
        resp = await client.get(f"/repos/{repo}/git/trees/HEAD?recursive=1")
    _raise_for_status(resp, f"fetch_tree({repo})")
    return [
        item
        for item in resp.json().get("tree", [])
        if item.get("path", "").endswith(".md") and item.get("type") == "blob"
    ]


async def fetch_blob(
    db: AsyncSession, user: User, repo: str, path: str
) -> tuple[str, str]:
    """Returns (decoded_content, blob_sha) for a file in the vault."""
    headers = await _auth_headers(db, user)
    encoded_path = url_quote(path, safe="/")
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, base_url=_BASE, headers=headers
    ) as client:
        resp = await client.get(f"/repos/{repo}/contents/{encoded_path}")
    _raise_for_status(resp, f"fetch_blob({path})")
    data = resp.json()
    raw_b64 = data.get("content", "").replace("\n", "")
    content = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
    return content, data.get("sha", "")


async def write_file(
    db: AsyncSession,
    user: User,
    repo: str,
    path: str,
    content: str,
    commit_message: str,
    existing_sha: str | None = None,
) -> dict[str, Any]:
    """Create or update a file in the vault. Returns {sha, path, html_url}."""
    headers = await _auth_headers(db, user)
    encoded_path = url_quote(path, safe="/")
    body: dict[str, Any] = {
        "message": commit_message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if existing_sha:
        body["sha"] = existing_sha
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, base_url=_BASE, headers=headers
    ) as client:
        resp = await client.put(f"/repos/{repo}/contents/{encoded_path}", json=body)
    _raise_for_status(resp, f"write_file({path})")
    file_data = resp.json().get("content", {})
    return {
        "sha": file_data.get("sha", ""),
        "path": path,
        "html_url": file_data.get("html_url", ""),
    }
