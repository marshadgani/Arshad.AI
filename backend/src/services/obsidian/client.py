"""GitHub transport for single-request Obsidian vault operations.

Reuses the user's linked GitHub OAuth token (same infrastructure as the
GitHub tools). Everything here is one HTTP round trip against the
Contents or Repos API; the multi-step Git Data commit protocol lives in
batch_commit.py, which shares this module's auth and error mapping rather
than re-deriving them.

Vault *location* is not resolved here — see config.py.
"""

from __future__ import annotations

import base64
import enum
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, NamedTuple
from urllib.parse import quote as url_quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.base import ProviderReauthRequired, ToolError
from ...tools.token_service import get_access_token

_BASE = "https://api.github.com"
_TIMEOUT = 20.0

logger = logging.getLogger(__name__)


class RepoVisibility(enum.Enum):
    """Tri-state result of a visibility check — never collapse to bool.

    ``UNKNOWN`` means GitHub's answer was inconclusive (network error,
    non-200, missing field), and callers must treat it as unsafe. A
    ``bool | None`` return would let ``if is_private:`` take the falsy
    branch on ``None`` — fail-open, with nothing in the type system to
    catch it. ``is_export_safe()`` decides that policy once so call sites
    can't reinvent it differently.
    """

    PRIVATE = "private"
    PUBLIC = "public"
    UNKNOWN = "unknown"

    def is_export_safe(self) -> bool:
        """True only when the repo is confirmed private. UNKNOWN and
        PUBLIC are both unsafe for domains that must never leave a
        public repo — fail-closed by construction, not by caller
        discipline."""
        return self is RepoVisibility.PRIVATE


class VaultFile(NamedTuple):
    """One (path, content) pair to write in a vault commit.

    Named rather than a bare ``tuple[str, str]``: transposing the two
    type-checks fine and would surface as a path collision in the vault.
    """

    path: str
    content: str


async def auth_headers(db: AsyncSession, user: User) -> dict[str, str]:
    access_token, _ = await get_access_token(db, user, "github")
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@asynccontextmanager
async def vault_client(
    db: AsyncSession, user: User
) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client pre-bound to api.github.com with the user's token."""
    headers = await auth_headers(db, user)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, base_url=_BASE, headers=headers
    ) as client:
        yield client


def raise_for_status(resp: httpx.Response, context: str) -> None:
    """Map a GitHub response onto the vault's error vocabulary."""
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
    async with vault_client(db, user) as client:
        resp = await client.get(f"/repos/{repo}/git/trees/HEAD?recursive=1")
    raise_for_status(resp, f"fetch_tree({repo})")
    return [
        item
        for item in resp.json().get("tree", [])
        if item.get("path", "").endswith(".md") and item.get("type") == "blob"
    ]


async def fetch_blob_with_client(
    client: httpx.AsyncClient, repo: str, path: str
) -> tuple[str, str]:
    """Returns (decoded_content, blob_sha) for a file in the vault.

    Takes an already-built, already-authenticated client so callers fetching
    many blobs in the same run (e.g. inbound vault sync) share one
    connection-pooled client and one token lookup instead of paying for a
    fresh TLS handshake and a fresh DB token round trip per file.
    """
    resp = await client.get(f"/repos/{repo}/contents/{url_quote(path, safe='/')}")
    raise_for_status(resp, f"fetch_blob({path})")
    data = resp.json()
    raw_b64 = data.get("content", "").replace("\n", "")
    content = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
    return content, data.get("sha", "")


async def fetch_blob(
    db: AsyncSession, user: User, repo: str, path: str
) -> tuple[str, str]:
    """Single-file convenience wrapper — opens its own client and token.

    Callers fetching more than one blob in the same run should build a
    ``vault_client`` once and call ``fetch_blob_with_client`` directly
    instead (see ``services/ingestion/obsidian.py``).
    """
    async with vault_client(db, user) as client:
        return await fetch_blob_with_client(client, repo, path)


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
    body: dict[str, Any] = {
        "message": commit_message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if existing_sha:
        body["sha"] = existing_sha
    async with vault_client(db, user) as client:
        resp = await client.put(
            f"/repos/{repo}/contents/{url_quote(path, safe='/')}", json=body
        )
    raise_for_status(resp, f"write_file({path})")
    file_data = resp.json().get("content", {})
    return {
        "sha": file_data.get("sha", ""),
        "path": path,
        "html_url": file_data.get("html_url", ""),
    }


async def repo_is_private(db: AsyncSession, user: User, repo: str) -> RepoVisibility:
    """Returns RepoVisibility.PRIVATE/PUBLIC for a confirmed repo, or
    RepoVisibility.UNKNOWN when visibility genuinely can't be determined
    (network error, non-200, missing 'private' key). Callers gating any
    decision on privacy should use RepoVisibility.is_export_safe() rather
    than comparing to PRIVATE/PUBLIC by hand, so UNKNOWN can never be
    mistaken for "not private"."""
    try:
        async with vault_client(db, user) as client:
            resp = await client.get(f"/repos/{repo}")
    except ProviderReauthRequired:
        return RepoVisibility.UNKNOWN
    except httpx.HTTPError as exc:
        logger.warning("repo_is_private(%s): request failed — %s", repo, exc)
        return RepoVisibility.UNKNOWN
    if resp.status_code != 200:
        return RepoVisibility.UNKNOWN
    data = resp.json()
    if "private" not in data:
        return RepoVisibility.UNKNOWN
    return RepoVisibility.PRIVATE if bool(data["private"]) else RepoVisibility.PUBLIC


__all__ = [
    "RepoVisibility",
    "VaultFile",
    "auth_headers",
    "fetch_blob",
    "fetch_blob_with_client",
    "fetch_tree",
    "raise_for_status",
    "repo_is_private",
    "vault_client",
    "write_file",
]
