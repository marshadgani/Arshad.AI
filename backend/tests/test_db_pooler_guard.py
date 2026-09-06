"""Unit tests for backend/src/models/db_pooler_guard.py.

Tests all critical paths:
  1. Session mode pooler (port 5432) — allowed
  2. Transaction mode pooler (port 6543) — blocked
  3. Direct Supabase connection — allowed
  4. Local docker URL — allowed
  5. Portless pooler URL — allowed (documents the None != 6543 behavior)
  6. Malformed/non-numeric port — blocked (fails safe, doesn't crash)
  7. Out-of-range port — blocked (fails safe, doesn't crash)
  8. Transaction mode with uppercase hostname — blocked (case-insensitive)
  9. 'pooler.supabase.com' appearing only in path, not hostname — allowed
  10. Transaction-mode port with pooler-style username but non-pooler host — blocked
"""

from __future__ import annotations

import pytest
from src.models.db_pooler_guard import is_pooler_url, reject_transaction_mode_pooler

PASSWORD = "7vr7McsvZy3!Gsk"


def test_session_mode_pooler_allowed():
    url = f"postgresql+asyncpg://postgres.ref:{PASSWORD}@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"
    reject_transaction_mode_pooler(url)  # must not raise


def test_transaction_mode_pooler_blocked():
    url = f"postgresql+asyncpg://postgres.ref:{PASSWORD}@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"
    with pytest.raises(RuntimeError, match="Transaction mode pooler"):
        reject_transaction_mode_pooler(url)


def test_direct_connection_allowed():
    url = f"postgresql+asyncpg://postgres:{PASSWORD}@db.ref.supabase.co:5432/postgres"
    reject_transaction_mode_pooler(url)  # must not raise


def test_local_docker_url_allowed():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/arshad_ai"
    reject_transaction_mode_pooler(url)  # must not raise


def test_portless_pooler_url_allowed():
    """No port specified — parsed.port is None, so it never equals 6543.

    Documents this as intended behavior: a portless pooler URL is treated
    as safe rather than guessed at. If Supabase ever serves Transaction
    mode without an explicit port, this assumption needs revisiting.
    """
    url = f"postgresql+asyncpg://postgres.ref:{PASSWORD}@aws-1-ap-northeast-1.pooler.supabase.com/postgres"
    reject_transaction_mode_pooler(url)  # must not raise


def test_malformed_port_fails_safe():
    url = f"postgresql+asyncpg://postgres:{PASSWORD}@db.ref.supabase.co:notaport/postgres"
    with pytest.raises(RuntimeError, match="Could not parse a port"):
        reject_transaction_mode_pooler(url)


def test_out_of_range_port_fails_safe():
    url = f"postgresql+asyncpg://postgres:{PASSWORD}@db.ref.supabase.co:99999999/postgres"
    with pytest.raises(RuntimeError, match="Could not parse a port"):
        reject_transaction_mode_pooler(url)


def test_transaction_mode_uppercase_hostname_blocked():
    url = f"postgresql+asyncpg://postgres.ref:{PASSWORD}@AWS-1-AP-NORTHEAST-1.POOLER.SUPABASE.COM:6543/postgres"
    with pytest.raises(RuntimeError, match="Transaction mode pooler"):
        reject_transaction_mode_pooler(url)


def test_pooler_substring_in_path_not_hostname_allowed():
    """'pooler.supabase.com' in the path/query must not false-positive."""
    url = f"postgresql+asyncpg://postgres:{PASSWORD}@localhost:6543/pooler.supabase.com"
    reject_transaction_mode_pooler(url)  # must not raise — host is localhost


def test_pooler_username_pattern_without_pooler_hostname_blocked():
    """Defense-in-depth: 'postgres.PROJECT_REF' username is itself a pooler
    signal even if Supabase serves it from a differently named host."""
    url = f"postgresql+asyncpg://postgres.ref:{PASSWORD}@custom-pooler-alias.example.com:6543/postgres"
    with pytest.raises(RuntimeError, match="Transaction mode pooler"):
        reject_transaction_mode_pooler(url)


class TestIsPoolerUrl:
    def test_hostname_match(self):
        url = "postgresql://u:p@aws-1.pooler.supabase.com:5432/db"
        assert is_pooler_url(url) is True

    def test_username_match(self):
        url = "postgresql://postgres.ref:p@custom-host.example.com:5432/db"
        assert is_pooler_url(url) is True

    def test_direct_connection_not_pooler(self):
        url = "postgresql://postgres:p@db.ref.supabase.co:5432/db"
        assert is_pooler_url(url) is False

    def test_local_docker_not_pooler(self):
        url = "postgresql://postgres:postgres@localhost:5432/db"
        assert is_pooler_url(url) is False
