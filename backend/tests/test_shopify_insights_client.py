"""Tests for execute_insights_query in backend/src/services/shopify/client.py.

httpx.AsyncClient.post is mocked; no real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.services.shopify.client import (
    MAX_INSIGHTS_PAGES,
    execute_insights_query,
)


def _page(nodes, has_next_page, end_cursor=None, errors=None):
    body = {
        "data": {
            "orders": {
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
                "edges": [{"node": n} for n in nodes],
            }
        }
    }
    if errors:
        body["errors"] = errors
    return body


def _node(order_id: str, created_at: str, amount: str) -> dict:
    return {
        "id": order_id,
        "createdAt": created_at,
        "currentTotalPriceSet": {"shopMoney": {"amount": amount}},
    }


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


@pytest.mark.asyncio
async def test_single_page_not_truncated():
    body = _page([_node("1", "2026-09-10T10:00:00Z", "10.00")], has_next_page=False)

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(body))
    ):
        result = await execute_insights_query(
            "shop.myshopify.com", "tok", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"
        )

    assert result["truncated"] is False
    # covered_through is only load-bearing when truncated is True (see
    # parse_insights); the field may still carry the last node's createdAt
    # on a non-truncated fetch, harmlessly unused by the parser.
    assert len(result["orders"]) == 1


@pytest.mark.asyncio
async def test_cursor_is_threaded_between_pages():
    page1 = _page(
        [_node("1", "2026-09-10T10:00:00Z", "10.00")], True, end_cursor="cursor-1"
    )
    page2 = _page([_node("2", "2026-09-11T10:00:00Z", "20.00")], False)

    mock_post = AsyncMock(side_effect=[_FakeResponse(page1), _FakeResponse(page2)])
    with patch("httpx.AsyncClient.post", new=mock_post):
        await execute_insights_query(
            "shop.myshopify.com", "tok", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"
        )

    second_call_kwargs = mock_post.call_args_list[1].kwargs
    assert second_call_kwargs["json"]["variables"]["after"] == "cursor-1"


@pytest.mark.asyncio
async def test_page_cap_reached_sets_truncated_and_covered_through():
    node = _node("1", "2026-09-10T10:00:00Z", "10.00")
    page = _page([node], has_next_page=True, end_cursor="next")

    mock_post = AsyncMock(return_value=_FakeResponse(page))
    with patch("httpx.AsyncClient.post", new=mock_post):
        result = await execute_insights_query(
            "shop.myshopify.com", "tok", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"
        )

    assert mock_post.call_count == MAX_INSIGHTS_PAGES
    assert result["truncated"] is True
    assert result["covered_through"] == "2026-09-10T10:00:00Z"


@pytest.mark.asyncio
async def test_time_budget_exceeded_sets_truncated():
    page = _page(
        [_node("1", "2026-09-10T10:00:00Z", "10.00")],
        has_next_page=True,
        end_cursor="c",
    )

    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(page)

    with (
        patch("httpx.AsyncClient.post", new=fake_post),
        patch(
            "src.services.shopify.client.time.monotonic",
            side_effect=[0, 0, 100, 100, 100, 100, 100, 100, 100, 100],
        ),
    ):
        result = await execute_insights_query(
            "shop.myshopify.com", "tok", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"
        )

    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_one_client_constructed_for_whole_loop():
    page1 = _page([_node("1", "2026-09-10T10:00:00Z", "10.00")], True, end_cursor="c1")
    page2 = _page([_node("2", "2026-09-11T10:00:00Z", "20.00")], False)

    mock_post = AsyncMock(side_effect=[_FakeResponse(page1), _FakeResponse(page2)])

    fake_client = AsyncMock()
    fake_client.post = mock_post
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    constructor = MagicMock(return_value=fake_client)
    with patch("src.services.shopify.client.httpx.AsyncClient", new=constructor):
        await execute_insights_query(
            "shop.myshopify.com", "tok", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"
        )

    # Exactly one AsyncClient was ever constructed for the whole two-page loop.
    assert constructor.call_count == 1
    assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_graphql_error_on_orders_alias_stops_loop_and_records_partial_failure():
    body = _page(
        [],
        has_next_page=False,
        errors=[
            {"message": "boom", "path": ["orders"], "extensions": {"code": "INTERNAL"}}
        ],
    )

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(body))
    ):
        result = await execute_insights_query(
            "shop.myshopify.com", "tok", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"
        )

    assert result["truncated"] is True
    assert "orders" in result["partial_failures"]


@pytest.mark.asyncio
async def test_query_string_includes_test_false():
    body = _page([], has_next_page=False)
    mock_post = AsyncMock(return_value=_FakeResponse(body))

    with patch("httpx.AsyncClient.post", new=mock_post):
        await execute_insights_query(
            "shop.myshopify.com", "tok", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"
        )

    sent_variables = mock_post.call_args.kwargs["json"]["variables"]
    assert "test:false" in sent_variables["ordersQuery"]
