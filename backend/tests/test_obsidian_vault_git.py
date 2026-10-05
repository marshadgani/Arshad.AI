"""Tests for obsidian_vault_git. _run_git (the subprocess boundary) is faked."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.ingestion import obsidian_vault_git as g
from src.services.ingestion.errors import IngestionError

TOKEN = "ghp_SENTINEL_TOKEN_123"
FILES = {"People/alice.md": "hello\n"}


def _tree(content):
    return f"100644 blob {g.blob_sha(content)}\tPeople/alice.md\n"


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class FakeGit:
    """Records git subcommands; behaviour overridable per subcommand."""

    def __init__(self, head=True, tree="", staged="People/alice.md", fail=None, push_errs=()):
        self.calls, self.envs = [], []
        self.head, self.tree, self.staged = head, tree, staged
        self.fail = fail or {}
        self.push_errs = list(push_errs)

    def __call__(self, args, cwd=None, env=None, timeout=0):
        sub = next(a for a in args if a in
                   {"clone", "rev-parse", "ls-tree", "add", "diff", "commit", "push"})
        self.calls.append((sub, list(args)))
        self.envs.append(env)
        if sub in self.fail:
            return _cp(1, "", self.fail[sub])
        if sub == "rev-parse":
            if args[-1] == "HEAD" and "--verify" in args:
                return _cp(0 if self.head else 128)
            return _cp(0, "deadbeef\n")
        if sub == "ls-tree":
            return _cp(0, self.tree)
        if sub == "diff":
            return _cp(0, self.staged)
        if sub == "push" and self.push_errs:
            return _cp(1, "", self.push_errs.pop(0))
        return _cp()

    @property
    def subs(self):
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_REPO_TOKEN", TOKEN)
    monkeypatch.delenv("OBSIDIAN_VAULT_REPO_URL", raising=False)
    monkeypatch.setattr(g, "RETRY_AFTER_CAP_SECONDS", 0)


async def _push(fake, files=FILES, msg="m"):
    with patch.object(g, "_run_git", fake):
        return await g.push_vault(files, msg)


def test_blob_sha_known_vectors():
    assert g.blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert g.blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


@pytest.mark.skipif(not __import__("shutil").which("git"), reason="git missing")
def test_blob_sha_matches_git():
    data = "café\n".encode()
    real = subprocess.run(["git", "hash-object", "--stdin"], input=data, capture_output=True, check=True)
    assert g.blob_sha(data) == real.stdout.decode().strip()


@pytest.mark.asyncio
async def test_empty_repo_first_push_treats_all_files_as_changed():
    fake = FakeGit(head=False)
    res = await _push(fake)
    assert res.status == "ok" and res.files_written == 1 and res.commit_sha == "deadbeef"
    assert "ls-tree" not in fake.subs
    assert fake.subs.index("add") < fake.subs.index("commit") < fake.subs.index("push")


@pytest.mark.asyncio
async def test_unchanged_content_is_noop_without_commit_or_push():
    tree = _tree(b'hello\n')
    fake = FakeGit(tree=tree)
    res = await _push(fake)
    assert (res.status, res.files_written, res.commit_sha) == ("no_changes", 0, None)
    assert not {"add", "commit", "push"} & set(fake.subs)


@pytest.mark.asyncio
async def test_only_changed_files_are_written_and_staged():
    tree = _tree(b'hello\n')
    files = {**FILES, "People/bob.md": "new\n"}
    fake = FakeGit(tree=tree)
    res = await _push(fake, files)
    assert res.files_written == 1
    add_args = next(a for s, a in fake.calls if s == "add")
    assert add_args[-1] == "People/bob.md" and "People/alice.md" not in add_args


@pytest.mark.asyncio
async def test_changed_content_commits_with_given_message():
    tree = _tree(b'old')
    fake = FakeGit(tree=tree)
    res = await _push(fake, msg="vault export: x")
    assert res.status == "ok"
    assert "vault export: x" in next(a for s, a in fake.calls if s == "commit")


@pytest.mark.asyncio
async def test_empty_staged_diff_is_second_line_noop():
    fake = FakeGit(head=False, staged="")
    res = await _push(fake)
    assert res.status == "no_changes" and "commit" not in fake.subs and "push" not in fake.subs


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../evil.md", "/etc/passwd", "People/../../evil.md"])
async def test_path_escape_rejected_before_commit(bad):
    fake = FakeGit(head=False)
    with pytest.raises(IngestionError, match="vault_path_escape"):
        await _push(fake, {bad: "x"})
    assert not {"add", "commit", "push"} & set(fake.subs)


@pytest.mark.asyncio
async def test_token_never_in_argv_remote_url_or_logs(caplog):
    fake = FakeGit(fail={"push": f"fatal: auth failed {TOKEN}"})
    with caplog.at_level(logging.DEBUG), pytest.raises(IngestionError) as exc:
        await _push(fake)
    assert TOKEN not in str(exc.value) and TOKEN not in caplog.text
    assert all(TOKEN not in " ".join(a) for _, a in fake.calls)
    clone = next(a for s, a in fake.calls if s == "clone")
    assert f"https://github.com/marshadgani/Arshad-Ideaverse.git" in clone
    assert fake.envs[0]["OBSIDIAN_VAULT_GIT_TOKEN"] == TOKEN
    assert fake.envs[0]["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.asyncio
async def test_token_not_in_result_and_askpass_removed():
    seen = {}
    fake = FakeGit(head=False)
    orig = fake.__call__

    def spy(args, **kw):
        seen["askpass"] = kw["env"]["GIT_ASKPASS"]
        return orig(args, **kw)

    res = await _push(spy)
    assert TOKEN not in repr(res)
    assert not Path(seen["askpass"]).exists()


@pytest.mark.asyncio
async def test_missing_token_raises_before_any_git_call(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_REPO_TOKEN")
    fake = FakeGit()
    with pytest.raises(IngestionError, match="vault_token_missing"):
        await _push(fake)
    assert fake.calls == []


def test_repo_url_default_and_override(monkeypatch):
    assert g.vault_repo_url() == "marshadgani/Arshad-Ideaverse"
    monkeypatch.setenv("OBSIDIAN_VAULT_REPO_URL", "o/v")
    assert g.vault_repo_url() == "o/v"


@pytest.mark.parametrize("bad", ["https://evil.com/x", "a@github.com:e/r.git", "../x/y", "o/r r", "a/b/c", "noslash"])
def test_malformed_repo_slug_rejected(bad, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_REPO_URL", bad)
    with pytest.raises(IngestionError, match="invalid_vault_repo"):
        g.vault_repo_url()


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["clone", "add", "commit", "push"])
async def test_step_failure_raises_named_error(step):
    fake = FakeGit(head=False, fail={step: "boom"})
    with pytest.raises(IngestionError, match=f"vault_git_{step}_failed"):
        await _push(fake)


@pytest.mark.asyncio
async def test_push_rate_limit_retries_then_succeeds():
    fake = FakeGit(head=False, push_errs=["error: 429 Too Many Requests", "rate limit exceeded"])
    res = await _push(fake)
    assert res.status == "ok" and fake.subs.count("push") == 3


@pytest.mark.asyncio
async def test_push_rate_limit_exhausted_raises():
    fake = FakeGit(head=False, push_errs=["rate limit exceeded"] * 5)
    with pytest.raises(IngestionError, match="rate_limited"):
        await _push(fake)
    assert fake.subs.count("push") == g.MAX_RETRIES


@pytest.mark.asyncio
async def test_non_rate_limit_push_error_not_retried():
    fake = FakeGit(head=False, push_errs=["rejected: non-fast-forward"])
    with pytest.raises(IngestionError, match="push_failed"):
        await _push(fake)
    assert fake.subs.count("push") == 1


@pytest.mark.asyncio
async def test_timeout_and_missing_git_binary_map_to_ingestion_error():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 1)):
        with pytest.raises(IngestionError, match="git_timeout"):
            await g.push_vault(FILES, "m")
    with patch("subprocess.run", side_effect=FileNotFoundError("git")):
        with pytest.raises(IngestionError, match="git_unavailable"):
            await g.push_vault(FILES, "m")


@pytest.mark.asyncio
async def test_temp_dir_removed_on_success_and_failure(monkeypatch):
    import tempfile
    made = []
    real = tempfile.TemporaryDirectory

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self.name)

    monkeypatch.setattr(g.tempfile, "TemporaryDirectory", Spy)
    await _push(FakeGit(head=False))
    with pytest.raises(IngestionError):
        await _push(FakeGit(head=False, fail={"clone": "x"}))
    assert len(made) == 2 and not any(Path(d).exists() for d in made)


@pytest.mark.skipif(not __import__("shutil").which("git"), reason="git missing")
@pytest.mark.asyncio
async def test_real_git_round_trip_idempotent_and_update(tmp_path, monkeypatch):
    """Real git against a local bare repo: first push, identical no-op, update."""
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    real_run = g._run_git

    def local(args, **kw):
        args = [str(bare) if a.startswith("https://github.com/") else a for a in args]
        return real_run(args, **kw)

    def count():
        return int(subprocess.run(["git", "-C", str(bare), "rev-list", "--count", "HEAD"],
                                  capture_output=True, text=True).stdout.strip() or 0)

    with patch.object(g, "_run_git", local):
        r1 = await g.push_vault(FILES, "one")
        r2 = await g.push_vault(FILES, "two")
        r3 = await g.push_vault({"People/alice.md": "changed\n"}, "three")
    assert (r1.status, r2.status, r3.status) == ("ok", "no_changes", "ok")
    assert count() == 2
    show = subprocess.run(["git", "-C", str(bare), "show", "HEAD:People/alice.md"], capture_output=True, text=True)
    assert show.stdout == "changed\n"
