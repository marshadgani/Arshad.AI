"""Unit tests for the credential-safe error primitives (FEAT-069).

Proves safe_detail()/log_detail() never render the exception instance —
the exact channel a credential (query-string API key) leaks through.
"""

from __future__ import annotations

import httpx
from src.utils.errors import LAST_ERROR_MAX_CHARS, log_detail, safe_detail


def _http_status_error(url: str, status_code: int = 401) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        "upstream rejected", request=request, response=response
    )


def test_safe_detail_strips_query_string_credential():
    exc = _http_status_error(
        "https://api.openweathermap.org/data/2.5/weather?appid=SUPERSECRETKEY"
    )
    detail = safe_detail(exc)
    assert "SUPERSECRETKEY" not in detail
    assert "?" not in detail
    assert "appid" not in detail
    assert detail == "HTTPStatusError (HTTP 401)"


def test_safe_detail_does_not_render_exception_args():
    # str(KeyError('bot_token')) == "'bot_token'" — proves args are never
    # surfaced; only the type name is.
    assert safe_detail(KeyError("bot_token")) == "KeyError"


def test_safe_detail_truncates_to_max_chars():
    class _Huge(Exception):
        pass

    _Huge.__name__ = "H" * (LAST_ERROR_MAX_CHARS + 100)
    assert len(safe_detail(_Huge())) == LAST_ERROR_MAX_CHARS


def test_safe_detail_generic_exception_is_type_name_only():
    assert safe_detail(ConnectionError("boom")) == "ConnectionError"


def test_log_detail_carries_host_and_path_but_not_query_or_secret():
    exc = _http_status_error(
        "https://api.stackexchange.com/2.3/me?site=stackoverflow&access_token=SECRETTOKEN",
        status_code=403,
    )
    detail = log_detail(exc)
    assert "api.stackexchange.com" in detail
    assert "/2.3/me" in detail
    assert "SECRETTOKEN" not in detail
    assert "access_token" not in detail
    assert "?" not in detail


def test_log_detail_falls_back_to_safe_detail_without_request():
    assert log_detail(ValueError("x")) == "ValueError"


def test_log_detail_handles_httpx_error_constructed_without_request():
    # httpx.ConnectError('refused') — as raised directly by a mocked
    # transport in tests, or a low-level connection failure before any
    # Request object exists — exposes `.request` as a property that
    # RAISES RuntimeError rather than returning None. log_detail must not
    # propagate that.
    assert log_detail(httpx.ConnectError("refused")) == "ConnectError"


def test_strip_url_drops_userinfo():
    from src.utils.errors import _strip_url

    assert _strip_url("https://user:pw@host.example/p?q=1") == "https://host.example/p"


def test_error_summary_is_alias_for_safe_detail():
    from src.utils.errors import error_summary

    exc = ValueError("plain message, no secret")
    assert error_summary(exc) == safe_detail(exc)
