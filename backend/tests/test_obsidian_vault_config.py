"""Static configuration hygiene tests for FEAT-166.

Linked requirements: REQ-005.
No DB, no network, no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
_ENV_EXAMPLE = _REPO_ROOT / "backend" / ".env.example"
_REQUIREMENTS = _REPO_ROOT / "backend" / "requirements.txt"
_GIT_MODULE = (
    _REPO_ROOT / "backend" / "src" / "services" / "ingestion" / "obsidian_vault_git.py"
)


# ---------------------------------------------------------------------------
# CFG1 — .env.example entries
# ---------------------------------------------------------------------------


def test_cfg1_env_example_has_vault_token_entry():
    """TC-CFG01a: .env.example contains OBSIDIAN_VAULT_REPO_TOKEN with empty value."""
    assert _ENV_EXAMPLE.exists(), f"{_ENV_EXAMPLE} not found"
    content = _ENV_EXAMPLE.read_text()

    assert "OBSIDIAN_VAULT_REPO_TOKEN" in content, (
        "OBSIDIAN_VAULT_REPO_TOKEN missing from backend/.env.example"
    )
    token_line_re = re.compile(r"^OBSIDIAN_VAULT_REPO_TOKEN\s*=\s*(.*)", re.MULTILINE)
    match = token_line_re.search(content)
    assert match, "Could not find OBSIDIAN_VAULT_REPO_TOKEN= line"
    token_value = match.group(1).strip()
    assert not re.search(r"ghp_|github_pat_", token_value), (
        f"Real GitHub token found in .env.example for OBSIDIAN_VAULT_REPO_TOKEN: '{token_value}'"
    )


def test_cfg1_env_example_has_vault_repo_url_entry():
    """TC-CFG01b: .env.example contains OBSIDIAN_VAULT_REPO_URL."""
    assert _ENV_EXAMPLE.exists()
    content = _ENV_EXAMPLE.read_text()
    assert "OBSIDIAN_VAULT_REPO_URL" in content, (
        "OBSIDIAN_VAULT_REPO_URL missing from backend/.env.example"
    )


# ---------------------------------------------------------------------------
# CFG3 — repo-wide secret hygiene
# ---------------------------------------------------------------------------


def test_cfg3_git_module_does_not_log_token():
    """TC-CFG03: obsidian_vault_git.py never passes 'token' to a logger call."""
    if not _GIT_MODULE.exists():
        pytest.skip("obsidian_vault_git.py not yet implemented")

    source = _GIT_MODULE.read_text()

    log_call_re = re.compile(
        r"logger\.(?:debug|info|warning|error|critical|exception)\s*\([^)]*token[^)]*\)",
        re.IGNORECASE,
    )
    matches = log_call_re.findall(source)
    suspicious = [
        m
        for m in matches
        if re.search(r"f['\"].*token|%.*token|format.*token", m, re.IGNORECASE)
    ]
    assert not suspicious, (
        "Possible token leak in logger call(s) in obsidian_vault_git.py:\n"
        + "\n".join(suspicious)
    )


def test_cfg3_no_hardcoded_token_in_git_module():
    """TC-CFG03b: No ghp_ or github_pat_ literal in obsidian_vault_git.py."""
    if not _GIT_MODULE.exists():
        pytest.skip("obsidian_vault_git.py not yet implemented")

    source = _GIT_MODULE.read_text()
    assert not re.search(r"ghp_[A-Za-z0-9]{36}", source), (
        "Hardcoded GitHub classic PAT (ghp_...) found in obsidian_vault_git.py"
    )
    assert not re.search(r"github_pat_[A-Za-z0-9_]{82}", source), (
        "Hardcoded GitHub fine-grained PAT found in obsidian_vault_git.py"
    )


def test_cfg3_requirements_no_token_in_tracked_files():
    """TC-CFG03c: No tracked source file under backend/src contains a ghp_ token literal."""
    src_dir = _REPO_ROOT / "backend" / "src"
    if not src_dir.exists():
        pytest.skip("backend/src not found")

    pat_re = re.compile(r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}")
    violations = []
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(errors="replace")
        if pat_re.search(content):
            violations.append(str(py_file))

    assert not violations, "Hardcoded GitHub token found in:\n" + "\n".join(violations)
