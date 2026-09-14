"""Regression test for the concurrent-blob-fetch fix in ingest().

Before this change, ``ingest()`` called ``fetch_blob(db, user, repo, path)``
once per changed file, sequentially — each call opened a brand-new
``httpx.AsyncClient`` (fresh TLS handshake to api.github.com) and re-ran
``get_access_token`` (two DB round trips + a decrypt) just to read one
file. For a vault sync touching N files that serialised N * (2 DB queries
+ TLS handshake + HTTP round trip) instead of sharing one client and one
token lookup across the whole run.

Runs via a bare ``asyncio.run`` inside a normal ``def test_...`` rather
than ``@pytest.mark.asyncio`` since pytest-asyncio isn't guaranteed to be
installed in every environment these tests run in — no DB session or
FastAPI app is needed, only the pure ``ingest()`` control flow.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from src.services.ingestion.obsidian import ingest
from src.services.obsidian.config import EXPORT_ROOT


class _FakeUser:
    id = uuid.uuid4()


def _tree_item(path: str, sha: str) -> dict:
    return {"path": path, "sha": sha, "type": "blob"}


def test_concurrent_fetch_single_client_and_error_isolation():
    """One vault_client() open for the whole run, unchanged files are
    never fetched, the export-root prefix is filtered before fetching,
    and one failing fetch doesn't prevent the others from being ingested."""
    user = _FakeUser()
    tree = [
        _tree_item("Notes/unchanged.md", "same-sha"),  # skip: sha matches
        _tree_item(f"{EXPORT_ROOT}Calendar/x.md", "sha-x"),  # skip: export root
        _tree_item("Notes/good.md", "sha-good"),
        _tree_item("Notes/bad.md", "sha-bad"),
    ]

    open_count = 0
    fetch_calls: list[str] = []

    class _Ctx:
        async def __aenter__(self):
            nonlocal open_count
            open_count += 1
            return "shared-client-sentinel"

        async def __aexit__(self, *exc):
            return False

    async def _fake_fetch_blob_with_client(client, repo, path):
        assert client == "shared-client-sentinel"
        fetch_calls.append(path)
        if path.endswith("bad.md"):
            raise RuntimeError("simulated GitHub error")
        return "---\ntitle: Good\n---\nBody text", f"blob-{path}"

    # db.execute is called twice by ingest(): first the SELECT of existing
    # (github_path, blob_sha) pairs, then the upsert statement. Distinguish
    # them by call order rather than statement introspection.
    call_order = {"n": 0}

    async def _execute(stmt):
        call_order["n"] += 1
        if call_order["n"] == 1:
            return [("Notes/unchanged.md", "same-sha")]
        return None

    class _FakeDB:
        execute = staticmethod(_execute)

        async def commit(self):
            pass

    with (
        patch(
            "src.services.ingestion.obsidian.fetch_tree",
            new=AsyncMock(return_value=tree),
        ),
        patch(
            "src.services.ingestion.obsidian.vault_client",
            side_effect=lambda d, u: _Ctx(),
        ),
        patch(
            "src.services.ingestion.obsidian.fetch_blob_with_client",
            new=_fake_fetch_blob_with_client,
        ),
        patch(
            "src.services.ingestion.obsidian.vault_repo",
            return_value="owner/vault",
        ),
        patch(
            "src.services.ingestion.obsidian.event_bus.publish",
            new=AsyncMock(),
        ),
    ):
        result = asyncio.run(ingest(user=user, db=_FakeDB(), payload={}))

    # Only the two non-skipped, non-export-root files were ever fetched.
    assert sorted(fetch_calls) == ["Notes/bad.md", "Notes/good.md"]

    # The whole run shared exactly one vault_client() context — not one
    # per fetched file (the original bug opened a new client per file).
    assert open_count == 1

    # One record failed, one succeeded, one was skipped (sha match), and
    # the export-root file was filtered out before fetching entirely.
    assert result["failed"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 1
    assert result["total"] == 4
