"""Unit tests for main.py's ENABLE_INPROCESS_WORKER startup validation.

Verifies that:
  - RENDER env + worker disabled → CRITICAL log emitted with
    'ENABLE_INPROCESS_WORKER' in message.
  - ENVIRONMENT=production + worker disabled → CRITICAL emitted.
  - Neither RENDER nor production + worker disabled → no CRITICAL, INFO only.
  - Worker enabled → no CRITICAL regardless of environment.

These call the REAL ``src.main._log_worker_mode``. They deliberately do not
start the actual lifespan, which probes the database and opens network
connections — but they must not reimplement the branch either: an earlier
revision of this file copied the if/else into the helper below, so it went on
passing no matter what main.py did, including if the CRITICAL block were
deleted outright. A test for a "you will silently get no syncs" warning that
can itself silently test nothing is the same bug one level up.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

from src.main import _log_worker_mode

# ── Helper — drive the real worker-mode logging under a given environment ───


def _run_worker_validation_branch(
    env_vars: dict, worker_enabled: bool
) -> list[logging.LogRecord]:
    """Call the real _log_worker_mode() under `env_vars`, capturing its logs."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    handler.setLevel(logging.DEBUG)

    _log = logging.getLogger("src.main")
    _log.addHandler(handler)
    try:
        with patch.dict(os.environ, env_vars, clear=False):
            _log_worker_mode(started=worker_enabled)
    finally:
        _log.removeHandler(handler)

    return records


# TC-050 ───────────────────────────────────────────────────────────────────────────
def test_render_env_worker_disabled_emits_critical():
    """TC-050: RENDER env set + worker disabled → CRITICAL log with
    'ENABLE_INPROCESS_WORKER' in message."""
    records = _run_worker_validation_branch({"RENDER": "true"}, worker_enabled=False)
    critical = [r for r in records if r.levelno == logging.CRITICAL]
    assert critical, "Expected at least one CRITICAL log record"
    assert "ENABLE_INPROCESS_WORKER" in critical[0].getMessage()


# TC-051 ───────────────────────────────────────────────────────────────────────────
def test_environment_production_worker_disabled_emits_critical():
    """TC-051: ENVIRONMENT=production + worker disabled → CRITICAL log."""
    env = {"ENVIRONMENT": "production"}
    if os.environ.get("RENDER"):
        env["RENDER"] = ""
    records = _run_worker_validation_branch(env, worker_enabled=False)
    critical = [r for r in records if r.levelno == logging.CRITICAL]
    assert critical, "Expected CRITICAL when ENVIRONMENT=production and worker disabled"


# TC-052 ───────────────────────────────────────────────────────────────────────────
def test_local_env_worker_disabled_no_critical():
    """TC-052: Neither RENDER nor ENVIRONMENT=production, worker disabled
    → no CRITICAL log (only INFO)."""
    env = {"RENDER": "", "ENVIRONMENT": "development"}
    records = _run_worker_validation_branch(env, worker_enabled=False)
    critical = [r for r in records if r.levelno == logging.CRITICAL]
    assert not critical, "CRITICAL should NOT be emitted in local/dev environment"


# TC-053 ───────────────────────────────────────────────────────────────────────────
def test_worker_enabled_no_warning_regardless_of_env():
    """TC-053: Worker enabled → no CRITICAL or WARNING regardless of env."""
    records = _run_worker_validation_branch(
        {"RENDER": "true", "ENVIRONMENT": "production"}, worker_enabled=True
    )
    bad = [r for r in records if r.levelno >= logging.WARNING]
    assert not bad, (
        "No WARNING/CRITICAL expected when worker enabled; got: "
        f"{[r.getMessage() for r in bad]}"
    )
