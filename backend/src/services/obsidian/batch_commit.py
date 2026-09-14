"""One-commit-per-run vault writes via the GitHub Git Data API.

Writing N notes with the Contents API means N commits, which trips
GitHub's secondary rate limits on a first-run backfill. The Git Data API
does it in one commit, at the cost of a five-step protocol: resolve the
base commit, create a blob per file, build a tree, create the commit,
fast-forward the ref. Each step is its own function below.
"""

from __future__ import annotations

import asyncio
import base64

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.base import ToolError
from .client import VaultFile, raise_for_status, vault_client

_BLOB_CONCURRENCY = 5

# A non-fast-forward ref update comes back as 422 ("Update is not a fast
# forward"), not 409 — checking only 409 let every real branch race fall
# through to the generic obsidian_api_error, hiding the one condition
# callers are meant to distinguish.
_REF_CONFLICT_STATUSES = (409, 422)


async def _resolve_base(client: httpx.AsyncClient, repo: str) -> tuple[str, str, str]:
    """Returns (branch, base_commit_sha, base_tree_sha) for the default branch."""
    repo_resp = await client.get(f"/repos/{repo}")
    raise_for_status(repo_resp, f"create_commit_batch({repo}): repo lookup")
    branch = repo_resp.json().get("default_branch", "main")

    ref_resp = await client.get(f"/repos/{repo}/git/ref/heads/{branch}")
    raise_for_status(ref_resp, f"create_commit_batch({repo}): ref lookup")
    base_commit_sha = ref_resp.json()["object"]["sha"]

    commit_resp = await client.get(f"/repos/{repo}/git/commits/{base_commit_sha}")
    raise_for_status(commit_resp, f"create_commit_batch({repo}): base commit")
    base_tree_sha = commit_resp.json()["tree"]["sha"]

    return branch, base_commit_sha, base_tree_sha


async def _create_blobs(
    client: httpx.AsyncClient, repo: str, files: list[VaultFile]
) -> list[dict[str, str]]:
    """Upload every file as a blob, at most _BLOB_CONCURRENCY at a time."""
    semaphore = asyncio.Semaphore(_BLOB_CONCURRENCY)

    async def _one(file: VaultFile) -> dict[str, str]:
        async with semaphore:
            resp = await client.post(
                f"/repos/{repo}/git/blobs",
                json={
                    "content": base64.b64encode(file.content.encode("utf-8")).decode(
                        "ascii"
                    ),
                    "encoding": "base64",
                },
            )
        raise_for_status(resp, f"create_commit_batch({repo}): blob {file.path}")
        return {
            "path": file.path,
            "mode": "100644",
            "type": "blob",
            "sha": resp.json()["sha"],
        }

    return list(await asyncio.gather(*(_one(f) for f in files)))


async def _create_tree(
    client: httpx.AsyncClient,
    repo: str,
    base_tree_sha: str,
    entries: list[dict[str, str]],
) -> str:
    resp = await client.post(
        f"/repos/{repo}/git/trees",
        json={"base_tree": base_tree_sha, "tree": entries},
    )
    raise_for_status(resp, f"create_commit_batch({repo}): tree")
    return str(resp.json()["sha"])


async def _create_commit(
    client: httpx.AsyncClient,
    repo: str,
    message: str,
    tree_sha: str,
    parent_sha: str,
) -> str:
    resp = await client.post(
        f"/repos/{repo}/git/commits",
        json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
    )
    raise_for_status(resp, f"create_commit_batch({repo}): commit")
    return str(resp.json()["sha"])


async def _fast_forward_ref(
    client: httpx.AsyncClient, repo: str, branch: str, commit_sha: str
) -> None:
    resp = await client.patch(
        f"/repos/{repo}/git/refs/heads/{branch}",
        json={"sha": commit_sha, "force": False},
    )
    if resp.status_code in _REF_CONFLICT_STATUSES:
        raise ToolError(
            "obsidian_ref_conflict",
            f"{branch} moved during export — retry on next run.",
        )
    raise_for_status(resp, f"create_commit_batch({repo}): ref update")


async def create_commit_batch(
    db: AsyncSession,
    user: User,
    repo: str,
    files: list[VaultFile],
    message: str,
) -> str:
    """Write every VaultFile as ONE commit. Returns the new commit sha.

    Raises ToolError('obsidian_ref_conflict') on a non-fast-forward ref
    update (someone pushed to the branch mid-run) — callers must not retry
    the same batch blindly; the orchestrator aborts the run cleanly
    instead, leaving the watermark untouched so the next run picks the
    data back up.
    """
    if not files:
        raise ToolError(
            "obsidian_empty_batch", "create_commit_batch called with no files."
        )

    async with vault_client(db, user) as client:
        branch, base_commit_sha, base_tree_sha = await _resolve_base(client, repo)
        entries = await _create_blobs(client, repo, files)
        tree_sha = await _create_tree(client, repo, base_tree_sha, entries)
        commit_sha = await _create_commit(
            client, repo, message, tree_sha, base_commit_sha
        )
        await _fast_forward_ref(client, repo, branch, commit_sha)

    return commit_sha


__all__ = ["create_commit_batch"]
