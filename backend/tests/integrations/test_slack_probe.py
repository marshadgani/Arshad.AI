"""Tests for the Slack parse_probe/parse_sync fix (FEAT-069).

Before this fix, an ok=false auth.test response raised a bare Exception
via a generator-throw hack, which _factory.py's connect()/sync() could
not catch (it only matched IntegrationError and httpx.HTTPError), so a
bad Slack token produced an unhandled 500 instead of a 400.
"""

from __future__ import annotations

import pytest
from src.integrations.base import IntegrationError
from src.integrations.project.bulk_providers import _require_slack_ok


def test_require_slack_ok_raises_integration_error_on_failure():
    with pytest.raises(IntegrationError) as exc_info:
        _require_slack_ok({"ok": False, "error": "invalid_auth"})
    assert exc_info.value.code == "slack_auth_failed"
    assert "invalid_auth" in exc_info.value.message


def test_require_slack_ok_code_is_fixed_not_upstream_derived():
    # A different Slack error string must not change the machine-readable
    # code — only the human-readable message varies.
    with pytest.raises(IntegrationError) as exc_info:
        _require_slack_ok({"ok": False, "error": "token_revoked"})
    assert exc_info.value.code == "slack_auth_failed"


def test_require_slack_ok_missing_ok_key_raises():
    with pytest.raises(IntegrationError):
        _require_slack_ok({})
    with pytest.raises(IntegrationError):
        _require_slack_ok(None)


def test_require_slack_ok_success_projection_is_not_widened():
    body = {
        "ok": True,
        "team": "Acme",
        "user": "arshad",
        "bot_id": "B123",
        "url": "https://acme.slack.com/",
        "user_id": "U123",
        "team_id": "T123",
    }
    result = _require_slack_ok(body)
    assert result == {"team": "Acme", "user": "arshad"}
