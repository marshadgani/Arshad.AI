"""PAT-authenticated git push to the external Obsidian vault repo.

Separate from ``obsidian_client.py`` (user OAuth + Contents API, read path).
This module clones the vault repo, writes the rendered files, and pushes one
commit — and only when something actually changed.

Credential handling: the token is read from ``OBSIDIAN_VAULT_REPO_TOKEN`` at
call time and handed to git through a ``GIT_ASKPASS`` helper that reads it
from the subprocess environment. It never appears in argv, the remote URL,
``.git/config``, a file on disk, a log line, or an exception message (every
captured stderr is scrubbed of the token before use).

Idempotency: ``blob_sha`` of each rendered file is compared with the blob SHA
in ``git ls-tree -r HEAD``; unchanged files are not written, and if nothing
differs the push is skipped (``status='no_changes'``). ``git diff --cached``
is a second check before committing.

Stale file pruning: vault files under ``People/`` and ``Projects/`` that are
present in HEAD but absent from the current render set (entities demoted to
private or deleted) are removed via ``git rm --cached`` in the same commit,
so the privacy invariant is maintained incrementally.

Rate limits: git subprocess output carries no HTTP headers, so a push failing
with a rate-limit message waits ``RETRY_AFTER_CAP_SECONDS`` unconditionally
(up to ``MAX_RETRIES`` attempts); any other failure raises immediately.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import IngestionError

logger = logging.getLogger(__name__)

RETRY_AFTER_CAP_SECONDS = 60
MAX_RETRIES = 3
_PATH_BATCH_SIZE = 500
TOTAL_OPERATION_TIMEOUT_SECONDS = 900
_PER_COMMAND_TIMEOUT_SECONDS = 300
_RATE_LIMIT_PATTERNS = (
    "rate limit exceeded",
    "too many requests",
    "returned error: 429",
)
_DEFAULT_REPO = "marshadgani/Arshad-Ideaverse"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TOKEN_ENV = "OBSIDIAN_VAULT_REPO_TOKEN"
_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    'case "$1" in\n'
    "  Username*) echo x-access-token ;;\n"
    '  *) echo "$OBSIDIAN_VAULT_GIT_TOKEN" ;;\n'
    "esac\n"
)
# Managed directories — stale files in these prefixes are pruned each export.
_MANAGED_PREFIXES = ("People/", "Projects/")


@dataclass(frozen=True)
class PushResult:
    status: str
    files_written: int
    commit_sha: str | None
    message: str


def vault_repo_url() -> str:
    raw = os.getenv("OBSIDIAN_VAULT_REPO_URL")
    # Treat a missing env var as "use default"; treat an explicitly set empty
    # string as a configuration error rather than silently falling back.
    slug = (_DEFAULT_REPO if raw is None else raw).strip()
    if not slug:
        raise IngestionError("invalid_vault_repo: expected owner/repo")
    if not _REPO_RE.match(slug):
        raise IngestionError("invalid_vault_repo: expected owner/repo")
    owner, _, repo_name = slug.partition("/")
    # Reject dot-only segments (e.g. "../evil") that would survive the regex.
    if not repo_name or set(owner) <= {"."} or set(repo_name) <= {"."}:
        raise IngestionError("invalid_vault_repo: dot-segment in owner/repo")
    return slug


def _clone_url(slug: str) -> str:
    """Return the HTTPS clone URL for *slug*.

    Extracted as a separate function so tests can patch it to redirect clones
    to a local bare repository without touching argv scrubbing or token logic.
    """
    return f"https://github.com/{slug}.git"


def blob_sha(content: bytes) -> str:
    """Git blob SHA (sha1 of ``blob <len>\\0`` + content), used only to detect unchanged files."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()  # noqa: S324


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def _run_git(
    args: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = _PER_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    logger.debug("git %s", args[0] if args else "")
    try:
        return subprocess.run(  # noqa: S603
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise IngestionError(f"git_timeout: git {args[0] if args else ''}") from None
    except OSError as exc:
        raise IngestionError(
            f"git_unavailable: cannot execute git ({type(exc).__name__})"
        ) from None


def _fail(
    step: str, proc: subprocess.CompletedProcess[str], token: str
) -> IngestionError:
    detail = _scrub(proc.stderr or "", token)[:500]
    logger.error("vault git %s failed: %s", step, detail)
    return IngestionError(f"vault_git_{step}_failed: {detail}")


def _existing_blobs(repo: str, env: dict[str, str], token: str) -> dict[str, str]:
    proc = _run_git(["ls-tree", "-r", "HEAD"], cwd=repo, env=env)
    if proc.returncode != 0:
        raise _fail("ls_tree", proc, token)
    blobs: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob":
            blobs[path] = parts[2]
    return blobs


def _write_files(repo: Path, files: dict[str, str]) -> None:
    root = repo.resolve()
    for rel, content in files.items():
        target = (root / rel).resolve()
        if root not in target.parents:
            raise IngestionError("vault_path_escape: refusing to write outside repo")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))


def _setup_git_env(tmp_dir: Path, token: str) -> dict[str, str]:
    """Write the askpass helper into ``tmp_dir`` and return the subprocess env.

    The token is placed in the env under a dedicated key read by the helper
    script — it never appears in argv or in the remote URL.
    """
    askpass = tmp_dir / "askpass.sh"
    askpass.write_text(_ASKPASS_SCRIPT)
    askpass.chmod(stat.S_IRWXU)
    base = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "GIT_SSL_CAINFO", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY") if k in os.environ}
    return {
        **base,
        "HOME": str(tmp_dir),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ASKPASS": str(askpass),
        "GIT_TERMINAL_PROMPT": "0",
        "OBSIDIAN_VAULT_GIT_TOKEN": token,
    }


def _detect_changed_files(
    files: dict[str, str],
    cwd: str,
    env: dict[str, str],
    token: str,
    has_head: bool,
) -> tuple[dict[str, str], list[str]]:
    """Return ``(changed, stale)`` relative to the current HEAD.

    *changed* — files whose content differs from HEAD (or all files when the
    repo has no HEAD).
    *stale* — paths under the managed prefixes (``People/``, ``Projects/``)
    that exist in HEAD but are absent from the current render set, meaning
    the underlying entity was deleted or demoted to private.

    When the repo has no HEAD (first push into an empty repo), every file is
    treated as changed and the stale list is empty.
    """
    if not has_head:
        return dict(files), []
    existing = _existing_blobs(cwd, env, token)
    changed = {
        path: content
        for path, content in files.items()
        if existing.get(path) != blob_sha(content.encode("utf-8"))
    }
    stale = [
        path
        for path in existing
        if any(path.startswith(p) for p in _MANAGED_PREFIXES) and path not in files
    ]
    return changed, stale


def _run_chunked(
    prefix: list[str],
    paths: list[str],
    cwd: str,
    env: dict[str, str],
    token: str,
    step: str,
) -> None:
    """Run a git path command in fixed-size batches to stay under ARG_MAX."""
    for i in range(0, len(paths), _PATH_BATCH_SIZE):
        proc = _run_git([*prefix, *paths[i : i + _PATH_BATCH_SIZE]], cwd=cwd, env=env)
        if proc.returncode != 0:
            raise _fail(step, proc, token)


def _stage_and_commit(
    repo: Path,
    cwd: str,
    changed: dict[str, str],
    stale: list[str],
    commit_message: str,
    env: dict[str, str],
    token: str,
) -> bool:
    """Write changed files, remove stale files, stage both, and commit.

    Returns ``True`` if a commit was created, ``False`` if ``git diff --cached``
    shows nothing staged (second-line idempotency guard).
    """
    if changed:
        _write_files(repo, changed)
        _run_chunked(["add", "--"], list(changed), cwd, env, token, "add")
    if stale:
        _run_chunked(["rm", "--cached", "--"], stale, cwd, env, token, "rm")
    proc = _run_git(["diff", "--cached", "--name-only"], cwd=cwd, env=env)
    if proc.returncode != 0:
        raise _fail("diff", proc, token)
    if not proc.stdout.strip():
        return False
    proc = _run_git(
        [
            "-c",
            "user.email=vault-export@arshad.ai",
            "-c",
            "user.name=ArshadAI",
            "commit",
            "-m",
            commit_message,
        ],
        cwd=cwd,
        env=env,
    )
    if proc.returncode != 0:
        raise _fail("commit", proc, token)
    return True


def _push_with_retry(
    cwd: str,
    env: dict[str, str],
    token: str,
    deadline: float,
) -> None:
    """Push HEAD to origin, retrying on rate-limit errors up to ``MAX_RETRIES``."""
    for attempt in range(1, MAX_RETRIES + 1):
        if time.monotonic() > deadline:
            raise IngestionError("vault_git_timeout: total operation timeout exceeded")
        proc = _run_git(["push", "origin", "HEAD"], cwd=cwd, env=env)
        if proc.returncode == 0:
            return
        stderr = (proc.stderr or "").lower()
        if not any(p in stderr for p in _RATE_LIMIT_PATTERNS):
            raise _fail("push", proc, token)
        if attempt == MAX_RETRIES:
            raise IngestionError("vault_git_rate_limited: retries exhausted")
        time.sleep(RETRY_AFTER_CAP_SECONDS)


def _push_all_sync(
    files: dict[str, str], repo_slug: str, token: str, commit_message: str
) -> PushResult:
    deadline = time.monotonic() + TOTAL_OPERATION_TIMEOUT_SECONDS
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        env = _setup_git_env(tmp_path, token)
        repo = tmp_path / "repo"

        proc = _run_git(
            ["clone", "--depth=1", _clone_url(repo_slug), str(repo)],
            env=env,
        )
        if proc.returncode != 0:
            raise _fail("clone", proc, token)

        cwd = str(repo)
        has_head = (
            _run_git(["rev-parse", "--verify", "HEAD"], cwd=cwd, env=env).returncode
            == 0
        )
        if not has_head:
            logger.info("vault repo %s has no commits; initial export", repo_slug)
        changed, stale = _detect_changed_files(files, cwd, env, token, has_head)
        if not changed and not stale:
            return PushResult("no_changes", 0, None, commit_message)

        committed = _stage_and_commit(
            repo, cwd, changed, stale, commit_message, env, token
        )
        if not committed:
            return PushResult("no_changes", 0, None, commit_message)

        _push_with_retry(cwd, env, token, deadline)
        head = _run_git(["rev-parse", "HEAD"], cwd=cwd, env=env)
        sha = head.stdout.strip() if head.returncode == 0 else None
        if not sha:
            logger.warning(
                "vault push succeeded but commit sha could not be read: %s",
                _scrub(head.stderr or "", token)[:200],
            )
        return PushResult("ok", len(changed), sha or None, commit_message)


async def push_vault(files: dict[str, str], commit_message: str) -> PushResult:
    """Clone the vault repo, write changed files, prune stale managed notes, commit and push.

    The token is read at call time. Git work runs in a worker thread. A
    ``no_changes`` status is a valid result and needs no retry. Pruning only
    removes the tip: git history keeps earlier versions, so the vault repo
    must stay private.
    """
    token = os.getenv(_TOKEN_ENV)
    if not token:
        raise IngestionError(f"vault_token_missing: set {_TOKEN_ENV}")
    slug = vault_repo_url()
    return await asyncio.to_thread(_push_all_sync, files, slug, token, commit_message)
