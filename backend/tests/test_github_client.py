"""Unit tests for ``src/tools/clients/github.py``'s status-code mapping.

FEAT-139 gap: nothing exercised this function directly before. GitHub has
no separate rate-limit error class -- 403 always maps to ToolError
('github_forbidden') regardless of remaining quota -- and 401 takes a
completely different path (ProviderReauthRequired, no retry, since GitHub
OAuth Apps issue no refresh token). A regression here would either mask a
scope-denial as a retryable error or silently swallow a 401 into a
generic ToolError, so both status codes and the success/no-content paths
are pinned explicitly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.tools.base import ProviderReauthRequired, ToolError
from src.tools.clients.github import request


def _mock_response(status_code, *, text="", content=b"", json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = content if content else text.encode()
    if json_body is not None:
        resp.json.return_value = json_body
    return resp


async def _call_with_response(resp):
    """Exercise ``request()`` against a mocked shared client.

    ``request()`` now fetches its HTTP client from the module-level
    keep-alive singleton (``_get_client``, see the pooling rationale in
    ``src/tools/clients/github.py``) rather than opening a fresh
    ``httpx.AsyncClient`` per call, so the client itself is mocked at that
    seam instead of patching ``httpx.AsyncClient`` directly — the same
    pattern used for the Whoop client's tests.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=resp)

    with (
        patch(
            "src.tools.clients.github.get_access_token",
            new_callable=AsyncMock,
            return_value=("fake_token", None),
        ),
        patch(
            "src.tools.clients.github._get_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ),
    ):
        return await request(
            db=mock_db, user=mock_user, method="GET", path="/repos/org/repo/issues"
        )


@pytest.mark.asyncio
async def test_401_raises_reauth_required_not_tool_error():
    """GitHub OAuth Apps issue no refresh token -- 401 must never be
    silently retried or reported as a generic ToolError."""
    resp = _mock_response(401, text="Bad credentials")

    with pytest.raises(ProviderReauthRequired):
        await _call_with_response(resp)


@pytest.mark.asyncio
async def test_403_with_ratelimit_exhausted_raises_github_forbidden():
    resp = _mock_response(
        403, text="API rate limit exceeded", content=b"API rate limit exceeded"
    )
    resp.headers = {"x-ratelimit-remaining": "0"}

    with pytest.raises(ToolError) as exc_info:
        await _call_with_response(resp)

    assert exc_info.value.code == "github_forbidden"


@pytest.mark.asyncio
async def test_403_with_quota_remaining_still_raises_github_forbidden():
    """403 has no separate rate-limit class -- a scope denial with quota
    remaining maps to the same code as an exhausted rate limit."""
    resp = _mock_response(
        403,
        text="Resource not accessible by integration",
        content=b"Resource not accessible",
    )
    resp.headers = {"x-ratelimit-remaining": "4999"}

    with pytest.raises(ToolError) as exc_info:
        await _call_with_response(resp)

    assert exc_info.value.code == "github_forbidden"


@pytest.mark.asyncio
async def test_5xx_raises_provider_http_error():
    resp = _mock_response(502, text="Bad Gateway")

    with pytest.raises(ToolError) as exc_info:
        await _call_with_response(resp)

    assert exc_info.value.code == "provider_http_error"


@pytest.mark.asyncio
async def test_4xx_non_401_403_raises_provider_request_failed():
    resp = _mock_response(422, text="Validation Failed")

    with pytest.raises(ToolError) as exc_info:
        await _call_with_response(resp)

    assert exc_info.value.code == "provider_request_failed"


@pytest.mark.asyncio
async def test_204_returns_none():
    resp = _mock_response(204)

    result = await _call_with_response(resp)

    assert result is None


@pytest.mark.asyncio
async def test_200_returns_parsed_json_body():
    resp = _mock_response(200, content=b"[]", json_body=[{"number": 1}])

    result = await _call_with_response(resp)

    assert result == [{"number": 1}]
