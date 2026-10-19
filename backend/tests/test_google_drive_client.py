"""Integration tests for src.services.drive._http.list_recent_files.

Uses httpx.MockTransport; no real network. NF-204, NF-205.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from src.services.drive._constants import _PAGE_CAP
from src.services.drive._http import list_recent_files

TOKEN = "fake-bearer-SENTINEL"


def _response(files, next_token=None, status=200):
    body = {"files": files}
    if next_token:
        body["nextPageToken"] = next_token
    return httpx.Response(status, json=body)


def _sentinel_file(n):
    return {
        "id": f"fid-{n}",
        "name": f"PLACEHOLDER-FILE-{n}.pdf",
        "modifiedTime": "2025-01-01T00:00:00Z",
        "webViewLink": f"https://drive.google.com/f/{n}",
    }


class _QueueTransport(httpx.AsyncBaseTransport):
    """Returns responses from a queue; counts calls and records request params."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.call_count = 0
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        self.requests.append(request)
        if not self._queue:
            return httpx.Response(500, json={"error": "queue exhausted"})
        return self._queue.pop(0)


async def _call(transport, limit=20, page_cap=_PAGE_CAP):
    """Patch the AsyncClient factory inside _http and call list_recent_files."""
    import src.services.drive._http as mod

    # Capture the real AsyncClient BEFORE patching so __aenter__ can use it
    # even after mod.httpx.AsyncClient (which is the same module object) is
    # replaced with PatchedClient.
    _RealAsyncClient = httpx.AsyncClient

    class PatchedClient:
        def __init__(self, **kwargs):
            self._transport = transport

        async def __aenter__(self):
            # Use the saved reference, NOT httpx.AsyncClient — that name now
            # points to PatchedClient itself and would recurse.
            client = _RealAsyncClient(transport=self._transport)
            return client

        async def __aexit__(self, *a):
            pass

    mod.httpx.AsyncClient = PatchedClient
    try:
        return await list_recent_files(TOKEN, limit=limit, page_cap=page_cap)
    finally:
        mod.httpx.AsyncClient = _RealAsyncClient


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# NF-204 — pagination caps
# ---------------------------------------------------------------------------


class TestPaginationCaps:
    def test_single_page_no_next_token(self):
        files = [_sentinel_file(i) for i in range(5)]
        t = _QueueTransport([_response(files)])
        result_files, truncated = run(_call(t, limit=20, page_cap=3))
        assert len(result_files) == 5
        assert truncated is False
        assert t.call_count == 1

    def test_page_cap_stops_after_n_calls(self):
        """NF-204: at most page_cap HTTP calls."""
        responses = [
            _response([_sentinel_file(i)], next_token=f"tok{i}") for i in range(10)
        ]
        t = _QueueTransport(responses)
        result_files, truncated = run(_call(t, limit=100, page_cap=3))
        assert t.call_count == 3
        assert truncated is True

    def test_truncated_false_when_last_page_has_no_token(self):
        r1 = _response([_sentinel_file(0)], next_token="tok1")
        r2 = _response([_sentinel_file(1)])  # no token
        t = _QueueTransport([r1, r2])
        _, truncated = run(_call(t, limit=100, page_cap=3))
        assert truncated is False
        assert t.call_count == 2

    def test_truncated_true_when_next_token_after_cap(self):
        responses = [
            _response([_sentinel_file(i)], next_token=f"tok{i}") for i in range(5)
        ]
        t = _QueueTransport(responses)
        _, truncated = run(_call(t, limit=100, page_cap=3))
        assert truncated is True

    def test_page_size_le_100(self):
        t = _QueueTransport([_response([])])
        run(_call(t, limit=200, page_cap=1))
        req = t.requests[0]
        params = dict(req.url.params)
        assert int(params["pageSize"]) <= 100


# ---------------------------------------------------------------------------
# NF-205 — read-only guard
# ---------------------------------------------------------------------------


class TestReadOnlyGuard:
    def test_only_get_requests_issued(self):
        t = _QueueTransport([_response([])])
        run(_call(t))
        for req in t.requests:
            assert req.method == "GET"

    def test_no_call_to_permissions_revoke(self):
        t = _QueueTransport([_response([])])
        run(_call(t))
        for req in t.requests:
            assert "revoke" not in str(req.url).lower()
            assert "permissions" not in str(req.url).lower() or "drive/v3/files" in str(
                req.url
            )

    def test_no_call_to_drive_activity_api(self):
        t = _QueueTransport([_response([])])
        run(_call(t))
        for req in t.requests:
            assert "activity" not in str(req.url).lower()

    def test_auth_header_present(self):
        t = _QueueTransport([_response([])])
        run(_call(t))
        assert t.requests[0].headers.get("authorization") == f"Bearer {TOKEN}"

    def test_url_targets_drive_v3_files(self):
        t = _QueueTransport([_response([])])
        run(_call(t))
        assert "drive/v3/files" in str(t.requests[0].url)


# ---------------------------------------------------------------------------
# Error raising
# ---------------------------------------------------------------------------


class TestErrorRaising:
    @pytest.mark.parametrize("status", [401, 403, 429, 500])
    def test_http_error_raises_http_status_error(self, status):
        t = _QueueTransport([httpx.Response(status, json={"error": "oops"})])
        with pytest.raises(httpx.HTTPStatusError):
            run(_call(t))

    def test_malformed_json_returns_empty_list(self):
        """Missing 'files' key: treat as empty, do not raise."""
        t = _QueueTransport([httpx.Response(200, json={"other": "data"})])
        files, truncated = run(_call(t))
        assert files == []
        assert truncated is False
