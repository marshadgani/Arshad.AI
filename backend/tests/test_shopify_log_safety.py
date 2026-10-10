"""Fetch-failure log lines must not carry the merchant's shop domain."""

from __future__ import annotations

import httpx
from src.services.shopify.gather import describe_error


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST", "https://secret-shop.myshopify.com/admin/api/graphql.json"
    )
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status, request=request)
    )


def test_http_error_logs_type_and_status_only():
    exc = _status_error(429)

    text = describe_error(exc)

    assert text == "HTTPStatusError 429"
    assert "myshopify" not in text


def test_error_without_response_logs_type_only():
    assert (
        describe_error(httpx.ConnectTimeout("https://secret-shop.myshopify.com"))
        == "ConnectTimeout"
    )
