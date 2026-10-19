"""Static-analysis guards for FEAT-123.

NF-202 (no new migration), NF-203 (no inline clock), NF-205 (read-only scope).
All tests are synchronous and do not invoke any application code.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).parent.parent
SRC = BACKEND / "src"
ALEMBIC_VERSIONS = BACKEND / "alembic" / "versions"

NEW_MODULES = [
    SRC / "services" / "drive" / "_classify.py",
    SRC / "services" / "drive" / "_http.py",
    SRC / "services" / "drive" / "_errors.py",
    SRC / "services" / "drive" / "service.py",
    SRC / "api" / "v1" / "drive.py",
]


# ---------------------------------------------------------------------------
# NF-202 — no new Alembic migration
# ---------------------------------------------------------------------------


class TestNoNewMigration:
    def test_no_feat123_migration_file_exists(self):
        """NF-202: FEAT-123 must not create a new migration file."""
        if not ALEMBIC_VERSIONS.exists():
            pytest.skip("alembic versions dir not found")
        migration_files = list(ALEMBIC_VERSIONS.glob("*.py"))
        for f in migration_files:
            assert "feat_123" not in f.name.lower(), (
                f"Unexpected FEAT-123 migration file found: {f.name}"
            )


# ---------------------------------------------------------------------------
# NF-203 — no inline clock calls in audit/http modules
# ---------------------------------------------------------------------------


class TestNoInlineClock:
    @pytest.mark.parametrize(
        "module_path",
        [
            SRC / "services" / "drive" / "_classify.py",
            SRC / "services" / "drive" / "_http.py",
            SRC / "services" / "drive" / "service.py",
        ],
    )
    def test_no_datetime_now_call(self, module_path):
        """NF-203: classify_files and http layer must never call datetime.now()."""
        if not module_path.exists():
            pytest.skip(f"{module_path} not built yet")
        source = module_path.read_text()
        assert "datetime.now(" not in source, (
            f"{module_path.name} contains an inline datetime.now() call — inject the clock instead"
        )
        assert "datetime.utcnow(" not in source, (
            f"{module_path.name} contains datetime.utcnow() — inject the clock instead"
        )

    @pytest.mark.parametrize(
        "module_path",
        [
            SRC / "services" / "drive" / "_classify.py",
            SRC / "services" / "drive" / "service.py",
        ],
    )
    def test_no_time_time_call(self, module_path):
        if not module_path.exists():
            pytest.skip(f"{module_path} not built yet")
        source = module_path.read_text()
        assert re.search(r"\btime\.time\b", source) is None, (
            f"{module_path.name} uses time.time() — inject the clock"
        )


# ---------------------------------------------------------------------------
# NF-201 — no f-string log calls with sensitive variables
# ---------------------------------------------------------------------------


class TestLoggerCallStyle:
    @pytest.mark.parametrize("module_path", NEW_MODULES)
    def test_no_fstring_in_logger_calls(self, module_path):
        """Logger calls must use %s args, not f-strings."""
        if not module_path.exists():
            pytest.skip(f"{module_path} not built yet")
        try:
            tree = ast.parse(module_path.read_text())
        except SyntaxError:
            pytest.fail(f"{module_path.name} has a syntax error")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in ("debug", "info", "warning", "error", "critical")
            ):
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            assert not isinstance(first_arg, ast.JoinedStr), (
                f"{module_path.name} line {node.lineno}: "
                f"logger.{func.attr}() uses an f-string — use %s format args instead"
            )


# ---------------------------------------------------------------------------
# NF-205 — read-only scope guard
# ---------------------------------------------------------------------------


class TestReadOnlyScope:
    def test_no_write_scope_string_in_drive_modules(self):
        # These are the OAuth scope suffixes that grant write access.
        # We look for them as the FULL scope URL segment (auth/drive, auth/drive.file,
        # etc.) rather than the bare word "drive" to avoid false-positives on FastAPI
        # router tags such as `tags=["drive"]`.
        write_scope_patterns = [
            'auth/drive"',  # full write scope: googleapis.com/auth/drive
            "auth/drive'",
            'auth/drive.file"',
            "auth/drive.file'",
            'auth/drive.appdata"',
            "auth/drive.appdata'",
        ]
        for module_path in NEW_MODULES:
            if not module_path.exists():
                continue
            source = module_path.read_text()
            for pattern in write_scope_patterns:
                assert pattern not in source, (
                    f"{module_path.name} references write scope (matched pattern {pattern!r})"
                )

    def test_drive_metadata_readonly_scope_unchanged_in_provider(self):
        provider = SRC / "auth" / "providers" / "google.py"
        if not provider.exists():
            pytest.skip("Google provider not found")
        source = provider.read_text()
        assert "drive.metadata.readonly" in source, (
            "drive.metadata.readonly scope was removed from the Google provider"
        )

    def test_no_activity_api_import(self):
        for module_path in NEW_MODULES:
            if not module_path.exists():
                continue
            source = module_path.read_text()
            assert "drive.activity" not in source, (
                f"{module_path.name} references drive.activity API (scope not granted)"
            )

    def test_no_delete_or_patch_http_calls(self):
        """No DELETE or PATCH/POST anywhere in the Drive HTTP client."""
        http_module = SRC / "services" / "drive" / "_http.py"
        if not http_module.exists():
            pytest.skip("_http.py not built yet")
        source = http_module.read_text().lower()
        for method in ("client.delete", "client.patch", "client.post"):
            assert method not in source, (
                f"_http.py issues a {method.upper()} call — Drive integration is read-only"
            )
