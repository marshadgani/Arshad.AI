"""Regression tests for main.py's fail-closed AUTH_ALLOWED_EMAILS check.

FEAT-144 security audit (2026-09-14): the previous version of this check
only logged CRITICAL and let the boot continue when AUTH_ALLOWED_EMAILS
was unset in production — a fail-*open* default that let any Google/GitHub
account sign in and permanently delete the deployment-wide project
API-key integrations. `_enforce_login_allowlist` now raises instead, the
same fail-fast contract already used by the SECRET_KEY check directly
above it in main.py.

These call the REAL ``src.main._enforce_login_allowlist`` under a patched
environment rather than reimplementing its branch, for the same reason
test_main_lifespan_worker_validation.py gives: a test that reimplements
the guard it's supposed to verify passes even if the real guard is
deleted.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from src.main import _enforce_login_allowlist


# TC-060 ───────────────────────────────────────────────────────────────────────────
def test_production_without_allowlist_raises():
    """RENDER set + AUTH_ALLOWED_EMAILS unset → RuntimeError, not a log line."""
    env = dict(os.environ)
    env["RENDER"] = "true"
    env.pop("AUTH_ALLOWED_EMAILS", None)
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="AUTH_ALLOWED_EMAILS"):
            _enforce_login_allowlist()


# TC-061 ───────────────────────────────────────────────────────────────────────────
def test_production_with_empty_allowlist_raises():
    """RENDER set + AUTH_ALLOWED_EMAILS='' (blank, not unset) → still raises."""
    env = dict(os.environ)
    env["RENDER"] = "true"
    env["AUTH_ALLOWED_EMAILS"] = "   "
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="AUTH_ALLOWED_EMAILS"):
            _enforce_login_allowlist()


# TC-062 ───────────────────────────────────────────────────────────────────────────
def test_production_with_allowlist_does_not_raise():
    """RENDER set + AUTH_ALLOWED_EMAILS populated → boots normally."""
    env = dict(os.environ)
    env["RENDER"] = "true"
    env["AUTH_ALLOWED_EMAILS"] = "owner@example.com"
    with patch.dict(os.environ, env, clear=True):
        _enforce_login_allowlist()  # must not raise


# TC-063 ───────────────────────────────────────────────────────────────────────────
def test_non_production_without_allowlist_does_not_raise():
    """Local/dev (neither RENDER nor ENVIRONMENT=production) → never raises,
    even with AUTH_ALLOWED_EMAILS unset — preserves today's dev-box behaviour."""
    env = dict(os.environ)
    env.pop("RENDER", None)
    env.pop("AUTH_ALLOWED_EMAILS", None)
    env["ENVIRONMENT"] = "development"
    with patch.dict(os.environ, env, clear=True):
        _enforce_login_allowlist()  # must not raise
