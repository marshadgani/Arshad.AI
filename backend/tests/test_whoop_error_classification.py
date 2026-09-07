"""Table tests for the pure Whoop error classifier.

_classify_whoop_error takes only the caught exception — no DB, no
Integration, no I/O — so these tests need no fixtures. See
backend/src/api/v1/whoop.py::_classify_whoop_error for the contract.
"""

from unittest.mock import MagicMock

import httpx
import pytest
from src.api.v1.whoop import _classify_whoop_error
from src.integrations.base import IntegrationError


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    request = MagicMock(spec=httpx.Request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.mark.parametrize(
    "exc,expected_needs_reauth,expected_fallback",
    [
        (IntegrationError("refresh_failed", "x"), True, 0),
        (IntegrationError("no_refresh_token", "x"), True, 0),
        (IntegrationError("not_connected", "x"), True, 0),
        (IntegrationError("token_decryption_failed", "x"), True, 0),
        (IntegrationError("sync_failed", "x"), False, 502),
        (_http_status_error(401), True, 0),
        (_http_status_error(403), True, 0),
        (_http_status_error(500), False, 502),
        (_http_status_error(429), False, 502),
    ],
)
def test_classify_whoop_error_table(exc, expected_needs_reauth, expected_fallback):
    needs_reauth, fallback_status = _classify_whoop_error(exc)
    assert needs_reauth is expected_needs_reauth
    if not expected_needs_reauth:
        assert fallback_status == expected_fallback


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectTimeout("timed out", request=MagicMock(spec=httpx.Request)),
        httpx.ReadTimeout("timed out", request=MagicMock(spec=httpx.Request)),
        httpx.ConnectError("refused", request=MagicMock(spec=httpx.Request)),
    ],
)
def test_classify_whoop_error_request_errors_never_touch_response(exc):
    """Regression guard: httpx.RequestError subclasses have NO `.response`
    attribute. A prior bug accessed `.response` unconditionally on any
    httpx.HTTPError, raising AttributeError while handling these exact
    exception types instead of degrading gracefully to a 502.
    """
    needs_reauth, fallback_status = _classify_whoop_error(exc)
    assert needs_reauth is False
    assert fallback_status == 502
