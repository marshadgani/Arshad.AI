"""Git Data API client for bulk, single-commit vault writes.

``obsidian_client.py`` stays the single-file Contents-API path used by
the user-facing chat tools (``obsidian_create_note`` / `_update_note`) —
that PUT-per-file model is correct for "write one note now".

FEAT-141's push-sync writes anywhere from a handful to thousands of
entity notes per run. Doing that via the Contents API means N commits
and N API calls; the Git Data API (tree + commit + ref) lets an entire
run land as ONE commit in ~5 calls regardless of how many files changed.
This module is that second, bulk-oriented client. It never touches
``obsidian_client.write_file``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User
from ..tools.base import ProviderReauthRequired, ToolError
from .obsidian_client import _auth_headers

_BASE = "https://api.github.com"
_TIMEOUT = 30.0
logger = logging.getLogger(__name__)


class OntologyRateLimitError(ToolError):
    """GitHub returned 403 + Retry-After, or x-ratelimit-remaining: 0."""

    def __init__(self, reset_at: str | None = None) -> None:
        super().__init__(
            code="ontology_rate_limited",
            message="GitHub API rate limit reached; sync deferred.",
        )
        self.reset_at = reset_at


class OntologyVaultPublicError(ToolError):
    """The configured vault repo is public.

    The ontology push mirrors Gmail subjects, calendar attendee email
    addresses and GitHub activity into markdown files. Committing that to
    a public repository is an irreversible disclosure of the user's — and
    every third party they correspond with — personal data, so a public
    vault is refused outright rather than merely warned about. Set
    ``OBSIDIAN_ALLOW_PUBLIC_VAULT=true`` only for a deliberately public
    demo vault.
    """

    def __init__(self, repo: str) -> None:
        super().__init__(
            code="ontology_vault_public",
            message=(
                f"Refusing to sync: vault repo '{repo}' is public. "
                "Make it private, or set OBSIDIAN_ALLOW_PUBLIC_VAULT=true "
                "if the exposure is intended."
            ),
        )


def _allow_public_vault() -> bool:
    return os.getenv("OBSIDIAN_ALLOW_PUBLIC_VAULT", "false").strip().lower() == "true"


class OntologyConcurrentWriteError(ToolError):
    """PATCH /git/refs/... returned 422 (non-fast-forward push)."""

    def __init__(self) -> None:
        super().__init__(
            code="ontology_concurrent_write",
            message="Vault ref moved during sync (concurrent push); retry deferred.",
        )


@dataclass(frozen=True)
class TreeEntry:
    """One entry for a Git Data tree. ``content`` for create/update;
    ``sha=None`` with no ``content`` deletes the path."""

    path: str
    content: str | None = None
    delete: bool = False


def _tree_item(entry: TreeEntry) -> dict[str, Any]:
    """``TreeEntry`` in the Git Data tree wire format. ``sha: None``
    removes the path; ``content`` creates or replaces it."""
    item: dict[str, Any] = {"path": entry.path, "mode": "100644", "type": "blob"}
    if entry.delete:
        item["sha"] = None
    else:
        item["content"] = entry.content or ""
    return item


def _raise_for_status(resp: httpx.Response, context: str) -> None:
    if resp.status_code == 401:
        raise ProviderReauthRequired("github")
    if resp.status_code == 403:
        retry_after = resp.headers.get("Retry-After")
        remaining = resp.headers.get("x-ratelimit-remaining")
        if retry_after or remaining == "0":
            raise OntologyRateLimitError(reset_at=resp.headers.get("x-ratelimit-reset"))
        raise ToolError("github_forbidden", f"{context}: access denied.")
    if resp.status_code == 422 and "refs" in context:
        raise OntologyConcurrentWriteError()
    if resp.status_code == 404:
        raise ToolError("obsidian_not_found", f"{context}: resource not found.")
    if resp.status_code >= 400:
        raise ToolError(
            "obsidian_api_error", f"{context}: GitHub returned {resp.status_code}."
        )


class ObsidianGitDataClient:
    """One GitHub-authenticated connection, reused for a whole run.

    A single ``commit_paths()`` call drives 7 GitHub requests
    (rate_limit, repo, ref, commit lookup, tree, commit, ref patch) — 13
    on a concurrent-write retry. Fetching auth headers and opening a
    fresh ``httpx.AsyncClient`` per request (the previous behaviour)
    meant 2 SQL SELECTs + a Fernet decrypt (``_auth_headers`` ->
    ``get_access_token``) AND a brand-new TCP+TLS handshake to
    ``api.github.com`` on every one of those calls, none of which is
    needed more than once per run: the token and connection are both
    valid for the whole request sequence. Headers are now fetched lazily
    on the first request and the same client/connection is kept open for
    every subsequent call; ``aclose()`` releases it once the run is done.
    """

    def __init__(self, *, db: AsyncSession, user: User, repo: str) -> None:
        self._db = db
        self._user = user
        self._repo = repo
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = await _auth_headers(self._db, self._user)
            self._client = httpx.AsyncClient(
                timeout=_TIMEOUT, base_url=_BASE, headers=headers
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        context: str,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """One authenticated GitHub call, raised-for-status. ``context``
        is the label errors are reported under (and is what tells
        ``_raise_for_status`` a 422 came from a ref update)."""
        client = await self._get_client()
        resp = await client.request(method, path, json=json)
        _raise_for_status(resp, context)
        return resp.json()

    async def get_rate_limit(self) -> dict[str, Any]:
        body = await self._request("GET", "/rate_limit", context="get_rate_limit")
        core = body.get("resources", {}).get("core", {})
        return {"remaining": core.get("remaining", 0), "reset_at": core.get("reset")}

    async def resolve_default_branch(self) -> str:
        """Default branch of the vault repo — and the one place the
        repo's visibility is checked. The ``/repos/{repo}`` payload
        carries ``private`` already, so gating the whole run on it here
        costs zero extra API calls and happens before any write call."""
        body = await self._request(
            "GET", f"/repos/{self._repo}", context="resolve_default_branch"
        )
        if body.get("private") is False and not _allow_public_vault():
            raise OntologyVaultPublicError(self._repo)
        return body.get("default_branch", "main")

    async def get_ref(self, branch: str) -> tuple[str, str]:
        """Returns (commit_sha, tree_sha) for the tip of ``branch``."""
        ref = await self._request(
            "GET", f"/repos/{self._repo}/git/refs/heads/{branch}", context="get_ref"
        )
        commit_sha = ref["object"]["sha"]
        commit = await self._request(
            "GET",
            f"/repos/{self._repo}/git/commits/{commit_sha}",
            context="get_ref(commit)",
        )
        return commit_sha, commit["tree"]["sha"]

    async def create_tree(self, base_tree_sha: str, entries: list[TreeEntry]) -> str:
        """Creates blobs inline via the tree endpoint's `content` field —
        GitHub creates the blob object server-side, one call per tree
        regardless of entry count. Returns the new tree SHA."""
        body = await self._request(
            "POST",
            f"/repos/{self._repo}/git/trees",
            context="create_tree",
            json={
                "base_tree": base_tree_sha,
                "tree": [_tree_item(entry) for entry in entries],
            },
        )
        return body["sha"]

    async def create_commit(self, tree_sha: str, parent_sha: str, message: str) -> str:
        body = await self._request(
            "POST",
            f"/repos/{self._repo}/git/commits",
            context="create_commit",
            json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        )
        return body["sha"]

    async def update_ref(self, branch: str, commit_sha: str) -> None:
        """Fast-forward-only — a ref that moved under us must surface as
        ``OntologyConcurrentWriteError``, never silently overwrite."""
        await self._request(
            "PATCH",
            f"/repos/{self._repo}/git/refs/heads/{branch}",
            context="update_ref(refs)",
            json={"sha": commit_sha, "force": False},
        )

    async def _commit_once(
        self, branch: str, entries: list[TreeEntry], message: str
    ) -> str:
        parent_sha, base_tree_sha = await self.get_ref(branch)
        tree_sha = await self.create_tree(base_tree_sha, entries)
        commit_sha = await self.create_commit(tree_sha, parent_sha, message)
        await self.update_ref(branch, commit_sha)
        return commit_sha

    async def commit_paths(
        self, *, branch: str, entries: list[TreeEntry], message: str
    ) -> str:
        """One-shot helper: get_ref -> create_tree -> create_commit ->
        update_ref. Returns the new commit SHA. Retries exactly once from
        a fresh ref on a concurrent-write 422; the second failure
        propagates as ``OntologyConcurrentWriteError`` for the caller to
        defer."""
        try:
            return await self._commit_once(branch, entries, message)
        except OntologyConcurrentWriteError:
            logger.warning(
                "ontology sync: ref moved during commit, retrying once (repo=%s)",
                self._repo,
            )
        return await self._commit_once(branch, entries, message)
