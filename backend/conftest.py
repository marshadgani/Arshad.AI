import base64
import os
import sys

import pytest

# Provide required env vars before any app module imports trigger startup
# validation. The values are fake — no actual connections are made in unit
# tests that don't exercise DB/Redis paths.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars-x")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
# src.auth.crypto._load_key() raises RuntimeError at call time (not import
# time) when this is unset — but apple_health tests exercise encrypt()/
# decrypt() directly, so every test run needs a valid 32-byte key.
os.environ.setdefault(
    "OAUTH_ENCRYPTION_KEY",
    base64.urlsafe_b64encode(b"test-key-32-bytes-for-tests-only").decode(),
)

# Allow `from src.xxx import ...` when pytest is run from backend/.
sys.path.insert(0, os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# Database-backed test gating
# ---------------------------------------------------------------------------
#
# `DATABASE_URL` is NOT a usable signal for "a real Postgres is reachable":
# the setdefault() above unconditionally installs a fake DSN so that app
# modules import cleanly in pure-unit runs. A test that guards itself with
# `if not os.environ.get("DATABASE_URL"): pytest.skip(...)` therefore never
# skips — it proceeds to open a connection to localhost:5432 and fails with
# ConnectionRefusedError on any machine without Postgres running.
#
# The explicit opt-in below is the single source of truth instead. Mark any
# test that needs a live database with `@pytest.mark.db`; it is skipped
# automatically unless RUN_DB_TESTS is set to a truthy value in an
# environment that also exports a real DATABASE_URL.

_FALSEY = {"", "0", "false", "no", "off"}


def db_tests_enabled() -> bool:
    """True when the environment has opted in to live-database tests."""
    return os.environ.get("RUN_DB_TESTS", "").strip().lower() not in _FALSEY


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_db: test needs a live Postgres database; skipped unless RUN_DB_TESTS=1",
    )


def pytest_collection_modifyitems(config, items):
    if db_tests_enabled():
        return
    skip_db = pytest.mark.skip(
        reason="requires a live Postgres database — set RUN_DB_TESTS=1 to enable"
    )
    for item in items:
        if "requires_db" in item.keywords:
            item.add_marker(skip_db)
