"""Tests for the Shopify HTTP transport layer (services/shopify/client.py).

Mocking pattern follows test_whoop_sync.py: monkeypatch httpx.AsyncClient
at the module boundary so no real network calls are made. The client
module is the only place Shopify wire bytes are read — these tests verify
that contract failures (4xx/5xx, missing access_token, GraphQL THROTTLED)
are handled correctly before the provider layer ever sees a result.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.integrations.base import IntegrationError
from src.services.shopify import client as shopify_client
from src.services.shopify.client import (
    ORDERS_PAGE_LIMIT,
    exchange_oauth_code,
    execute_dashboard_query,
)


# ── helpers ──────────────────────────────────────────────────────────────


def _mock_httpx_client(response: MagicMock) -> MagicMock:
    """Return a mock httpx.AsyncClient context manager that yields a client
    whose .post() always returns `response`.
    """
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _ok_response(body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=body)
    resp.text = ""
    return resp


def _error_response(status: int, text: str = "error") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            f"HTTP {status}", request=MagicMock(), response=MagicMock()
        )
    )
    resp.json = MagicMock(return_value={})
    return resp


# ── exchange_oauth_code — happy path ──────────────────────────────────────


@pytest.mark.asyncio
async def test_exchange_oauth_code_returns_token_response_on_success(monkeypatch):
    token_body = {"access_token": "shpat_abc123", "scope": "read_orders"}
    mock_client = _mock_httpx_client(_ok_response(token_body))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    result = await exchange_oauth_code(
        shop="mystore.myshopify.com",
        client_id="cid",
        client_secret="csecret",
        code="authcode",
    )

    assert result["access_token"] == "shpat_abc123"
    assert result["scope"] == "read_orders"


@pytest.mark.asyncio
async def test_exchange_oauth_code_posts_to_shop_specific_token_endpoint(monkeypatch):
    token_body = {"access_token": "tok"}
    mock_client = _mock_httpx_client(_ok_response(token_body))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    await exchange_oauth_code(
        shop="unique.myshopify.com",
        client_id="cid",
        client_secret="csecret",
        code="c",
    )

    call_url = mock_client.post.call_args[0][0]
    assert "unique.myshopify.com" in call_url
    assert "admin/oauth/access_token" in call_url


# ── exchange_oauth_code — error paths ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 500, 503])
async def test_exchange_oauth_code_raises_integration_error_on_http_error(
    monkeypatch, status_code
):
    """Any 4xx/5xx from Shopify's token endpoint must raise IntegrationError
    rather than returning a partial result — a missing token has no safe
    fallback.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = f"Shopify said {status_code}"
    resp.raise_for_status = MagicMock()  # client.py checks status_code directly
    resp.json = MagicMock(return_value={})
    mock_client = _mock_httpx_client(resp)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await exchange_oauth_code(
            shop="mystore.myshopify.com",
            client_id="cid",
            client_secret="csecret",
            code="code",
        )
    assert exc_info.value.code == "token_exchange_failed"


@pytest.mark.asyncio
async def test_exchange_oauth_code_raises_when_access_token_missing_from_response(
    monkeypatch,
):
    """Shopify can return HTTP 200 with a body that lacks 'access_token'
    (e.g. an invalid code). That must raise rather than hand back an empty
    dict that silently propagates to the DB as a null credential.
    """
    mock_client = _mock_httpx_client(_ok_response({"error": "invalid_code"}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(IntegrationError) as exc_info:
        await exchange_oauth_code(
            shop="mystore.myshopify.com",
            client_id="cid",
            client_secret="csecret",
            code="bad",
        )
    assert exc_info.value.code == "no_access_token"


# ── execute_dashboard_query — happy path ─────────────────────────────────


def _dashboard_graphql_body(
    orders: list | None = None,
    has_next: bool = False,
    orders_count: int = 3,
    variants: list | None = None,
) -> dict:
    return {
        "data": {
            "orders": {
                "pageInfo": {"hasNextPage": has_next},
                "edges": [{"node": o} for o in (orders or [])],
            },
            "ordersCount": {"count": orders_count, "precision": "exact"},
            "productVariants": {
                "pageInfo": {"hasNextPage": False},
                "edges": [{"node": v} for v in (variants or [])],
            },
        }
    }


@pytest.mark.asyncio
async def test_execute_dashboard_query_returns_orders_and_variants(monkeypatch):
    body = _dashboard_graphql_body(
        orders=[{"id": "gid://shopify/Order/1", "name": "#1001"}],
        variants=[{"id": "gid://shopify/ProductVariant/99"}],
    )
    mock_client = _mock_httpx_client(_ok_response(body))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    result = await execute_dashboard_query(
        "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
    )

    assert len(result["orders"]) == 1
    assert result["orders"][0]["name"] == "#1001"
    assert len(result["variants"]) == 1
    assert result["orders_count"] == 3
    assert result["orders_page_limit"] == ORDERS_PAGE_LIMIT


@pytest.mark.asyncio
async def test_execute_dashboard_query_reports_has_next_page_when_truncated(monkeypatch):
    """When Shopify signals there are more orders than the page limit,
    orders_has_next_page must be True so the consumer can show a truncation
    warning rather than claim the count is exact.
    """
    body = _dashboard_graphql_body(has_next=True)
    mock_client = _mock_httpx_client(_ok_response(body))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    result = await execute_dashboard_query(
        "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
    )

    assert result["orders_has_next_page"] is True


@pytest.mark.asyncio
async def test_execute_dashboard_query_returns_empty_lists_on_missing_data(monkeypatch):
    """A response with no data keys must not raise — it yields empty lists
    and None counts so the dashboard can render its zero-state.
    """
    mock_client = _mock_httpx_client(_ok_response({"data": {}}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    result = await execute_dashboard_query(
        "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
    )

    assert result["orders"] == []
    assert result["variants"] == []
    assert result["orders_count"] is None


# ── execute_dashboard_query — GraphQL partial failures ───────────────────


@pytest.mark.asyncio
async def test_execute_dashboard_query_reports_partial_failures_from_graphql_errors(
    monkeypatch,
):
    """GraphQL returns HTTP 200 even when an alias fails. partial_failures
    must list the affected alias so the caller can render a partial result
    rather than silently dropping data.
    """
    body = {
        "data": {"orders": {"pageInfo": {"hasNextPage": False}, "edges": []}, "ordersCount": {"count": 0, "precision": "exact"}, "productVariants": {"pageInfo": {"hasNextPage": False}, "edges": []}},
        "errors": [{"path": ["productVariants"], "message": "Access denied", "extensions": {"code": "ACCESS_DENIED"}}],
    }
    mock_client = _mock_httpx_client(_ok_response(body))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    result = await execute_dashboard_query(
        "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
    )

    assert "productVariants" in result["partial_failures"]


@pytest.mark.asyncio
async def test_execute_dashboard_query_returns_empty_partial_failures_on_clean_response(
    monkeypatch,
):
    body = _dashboard_graphql_body()
    mock_client = _mock_httpx_client(_ok_response(body))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    result = await execute_dashboard_query(
        "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
    )

    assert result["partial_failures"] == []


# ── _post_with_retry — THROTTLED retry behaviour ─────────────────────────


@pytest.mark.asyncio
async def test_post_with_retry_retries_once_on_throttled_error(monkeypatch):
    """When Shopify returns a THROTTLED GraphQL error the first call, the
    helper must sleep and retry exactly once. On the second call, if the
    throttle is gone, the result is returned without further retries.
    """
    throttled_body = {
        "errors": [
            {
                "message": "Throttled",
                "extensions": {
                    "code": "THROTTLED",
                    "cost": {"throttleStatus": {"currentlyAvailable": 0}},
                },
            }
        ]
    }
    clean_body = _dashboard_graphql_body()

    responses = [_ok_response(throttled_body), _ok_response(clean_body)]
    call_count = 0

    async def _fake_post(*args, **kwargs):
        nonlocal call_count
        r = responses[call_count]
        call_count += 1
        return r

    mock_client = MagicMock()
    mock_client.post = _fake_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
    monkeypatch.setattr(shopify_client.asyncio, "sleep", AsyncMock())

    result = await execute_dashboard_query(
        "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
    )

    assert call_count == 2
    assert result["orders"] == []


@pytest.mark.asyncio
async def test_post_with_retry_does_not_retry_more_than_once_on_persistent_throttle(
    monkeypatch,
):
    """MAX_THROTTLE_RETRIES is 1. After one retry the result is returned
    regardless of whether THROTTLED is still present — infinite retry loops
    are not permitted.
    """
    throttled_body = {
        "errors": [
            {
                "message": "Throttled",
                "extensions": {
                    "code": "THROTTLED",
                    "cost": {"throttleStatus": {"currentlyAvailable": 0}},
                },
            }
        ],
        "data": {
            "orders": {"pageInfo": {"hasNextPage": False}, "edges": []},
            "ordersCount": {"count": 0, "precision": "exact"},
            "productVariants": {"pageInfo": {"hasNextPage": False}, "edges": []},
        },
    }
    call_count = 0

    async def _fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _ok_response(throttled_body)

    mock_client = MagicMock()
    mock_client.post = _fake_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
    monkeypatch.setattr(shopify_client.asyncio, "sleep", AsyncMock())

    await execute_dashboard_query(
        "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
    )

    # 1 initial attempt + 1 retry = 2 total, never 3+
    assert call_count == 2


@pytest.mark.asyncio
async def test_post_with_retry_raises_on_http_error_status(monkeypatch):
    """A 5xx from Shopify's GraphQL endpoint (rare, but real during outages)
    must propagate as an httpx.HTTPStatusError rather than silently returning
    an empty result — execute_dashboard_query's caller decides how to handle it.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 500
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
    )

    mock_client = _mock_httpx_client(resp)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(httpx.HTTPStatusError):
        await execute_dashboard_query(
            "mystore.myshopify.com", "tok", "2026-09-01", "2026-09-01"
        )
