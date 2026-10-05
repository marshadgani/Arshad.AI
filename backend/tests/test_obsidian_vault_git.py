"""Unit tests for the vault git client — subprocess is faked."""

from __future__ import annotations

import logging
import subprocess
from unittest.mock import patch

import pytest
from src.services.ingestion import obsidian_vault_git as g
from src.services.ingestion.errors import IngestionError

TOKEN = "github_pat_SECRET_TOKEN_VALUE"


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


class FakeGit:
    def __init__(self, has_head=True, tree=None, push_results=None):
        self.has_head = has_head
        self.tree = tree or {}
        self.push_results = list(push_results or [_cp()])
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []

    def __call__(self, args, cwd=None, env=None, timeout=0):
        self.calls.append(args)
        self.envs.append(env or {})
        sub = next(
            a
            for a in args
            if a in {"clone", "rev-parse", "ls-tree", "add", "diff", "commit", "push"}
        )
        if sub == "rev-parse" and "--verify" in args:
            return _cp(0 if self.has_head else 1)
        if sub == "rev-parse":
            return _cp(out="abc123\n")
        if sub == "ls-tree":
            return _cp(
                out="".join(f"100644 blob {s}\t{p}\n" for p, s in self.tree.items())
            )
        if sub == "diff":
            return _cp(out="changed.md\n")
        if sub == "push":
            return (
                self.push_results.pop(0)
                if len(self.push_results) > 1
                else self.push_results[0]
            )
        return _cp()

    def subs(self):
        return [
            next(a for a in c if not a.startswith("-") and "=" not in a)
            for c in self.calls
        ]


def _run(fake, files=None):
    files = files if files is not None else {"People/a.md": "hello"}
    with patch.object(g, "_run_git", fake), patch.object(g.time, "sleep") as sleep:
        result = g._push_all_sync(files, "marshadgani/obsidian-vault", TOKEN, "msg")
    return result, sleep


def test_blob_sha_pure_function() -> None:
    assert g.blob_sha(b"hello") == "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"


def test_empty_repo_first_push() -> None:
    fake = FakeGit(has_head=False)
    result, _ = _run(fake)
    assert result.status == "ok" and result.files_written == 1
    assert "ls-tree" not in fake.subs()
    assert {"add", "commit", "push"} <= set(fake.subs())


def test_no_changes_skips_push() -> None:
    fake = FakeGit(tree={"People/a.md": g.blob_sha(b"hello")})
    result, _ = _run(fake)
    assert result.status == "no_changes"
    assert not {"add", "commit", "push"} & set(fake.subs())


def test_partial_change_idempotency(tmp_path) -> None:
    fake = FakeGit(tree={"People/a.md": g.blob_sha(b"hello")})
    result, _ = _run(fake, {"People/a.md": "hello", "People/b.md": "new"})
    assert result.files_written == 1
    add = next(c for c in fake.calls if "add" in c)
    assert "People/b.md" in add and "People/a.md" not in add


def test_askpass_script_not_in_args() -> None:
    fake = FakeGit()
    _run(fake)
    assert not any(TOKEN in a for c in fake.calls for a in c)
    assert "GIT_ASKPASS" in fake.envs[0]
    assert fake.envs[0]["GIT_TERMINAL_PROMPT"] == "0"


def test_token_not_in_logs_or_errors(caplog) -> None:
    fake = FakeGit(push_results=[_cp(1, err=f"fatal: auth failed for {TOKEN}")])
    with caplog.at_level(logging.DEBUG), pytest.raises(IngestionError) as exc:
        _run(fake)
    assert TOKEN not in str(exc.value)
    assert TOKEN not in caplog.text


def test_retry_after_cap_honored() -> None:
    fake = FakeGit(
        push_results=[_cp(1, err="remote error: rate limit exceeded"), _cp()]
    )
    result, sleep = _run(fake)
    sleep.assert_called_once_with(g.RETRY_AFTER_CAP_SECONDS)
    assert fake.subs().count("push") == 2
    assert result.status == "ok"


def test_rate_limit_retries_exhausted_raises() -> None:
    fake = FakeGit(push_results=[_cp(1, err="too many requests")])
    with pytest.raises(IngestionError):
        _run(fake)
    assert fake.subs().count("push") == g.MAX_RETRIES


def test_non_rate_limit_failure_not_retried() -> None:
    fake = FakeGit(push_results=[_cp(1, err="permission denied")])
    with pytest.raises(IngestionError):
        _run(fake)
    assert fake.subs().count("push") == 1


def test_path_escape_rejected() -> None:
    with pytest.raises(IngestionError):
        _run(FakeGit(), {"../evil.md": "x"})


@pytest.mark.asyncio
async def test_push_vault_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("OBSIDIAN_VAULT_REPO_TOKEN", raising=False)
    with pytest.raises(IngestionError):
        await g.push_vault({}, "m")


def test_vault_repo_url_validates(monkeypatch) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_REPO_URL", "x/y; rm -rf")
    with pytest.raises(IngestionError):
        g.vault_repo_url()
