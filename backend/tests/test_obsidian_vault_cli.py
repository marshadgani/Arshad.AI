"""Unit tests for scripts/obsidian_vault_export.py CLI.

No HTTP surface, no subprocess, no real DB.
Linked requirements: REQ-007.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The CLI script lives in scripts/ which is at the repo root.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# C1 — User resolution order
# ---------------------------------------------------------------------------


def test_c1_user_id_arg_wins(monkeypatch):
    """TC-C01: --user-id arg wins over env var."""
    explicit_uid = str(uuid.uuid4())
    env_uid = str(uuid.uuid4())

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    inserted_objects = []

    def fake_add(obj):
        inserted_objects.append(obj)

    mock_session.add = fake_add

    monkeypatch.setenv("OBSIDIAN_VAULT_EXPORT_USER_ID", env_uid)
    monkeypatch.setattr(
        sys, "argv", ["obsidian_vault_export.py", "--user-id", explicit_uid]
    )

    if "obsidian_vault_export" in sys.modules:
        del sys.modules["obsidian_vault_export"]

    with patch("src.models.database.AsyncSessionLocal") as factory:
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        try:
            import obsidian_vault_export as cli  # type: ignore[import]

            cli.main()
        except SystemExit as e:
            assert e.code == 0 or e.code is None

    if inserted_objects:
        assert str(inserted_objects[0].user_id) == explicit_uid


# ---------------------------------------------------------------------------
# C2 — Ambiguous or zero users exits with code 2
# ---------------------------------------------------------------------------


def test_c2_zero_users_exits_code_2(monkeypatch):
    """TC-C02: No users and no --user-id exits with code 2."""
    monkeypatch.delenv("OBSIDIAN_VAULT_EXPORT_USER_ID", raising=False)
    monkeypatch.setattr(sys, "argv", ["obsidian_vault_export.py"])

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    # execute() returns a result with .all() == [] (no users)
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[])
    mock_session.execute = AsyncMock(return_value=mock_result)

    if "obsidian_vault_export" in sys.modules:
        del sys.modules["obsidian_vault_export"]

    with patch("src.models.database.AsyncSessionLocal") as factory:
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(SystemExit) as exc:
            import obsidian_vault_export as cli  # type: ignore[import]

            cli.main()
        assert exc.value.code == 2

    mock_session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# C3 — Invalid UUID exits non-zero
# ---------------------------------------------------------------------------


def test_c3_invalid_uuid_exits_nonzero(monkeypatch):
    """TC-C03: Malformed --user-id exits non-zero with clear message, inserts nothing."""
    monkeypatch.setattr(
        sys, "argv", ["obsidian_vault_export.py", "--user-id", "not-a-uuid!!!"]
    )

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    if "obsidian_vault_export" in sys.modules:
        del sys.modules["obsidian_vault_export"]

    with patch("src.models.database.AsyncSessionLocal") as factory:
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(SystemExit) as exc:
            import obsidian_vault_export as cli  # type: ignore[import]

            cli.main()
        assert exc.value.code != 0

    mock_session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# C4 — Row contents
# ---------------------------------------------------------------------------


def test_c4_row_contents(monkeypatch, capsys):
    """TC-C04: Inserted DagTriggerQueue has correct dag_id, status, payload, and printed UUID."""
    explicit_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        sys, "argv", ["obsidian_vault_export.py", "--user-id", explicit_uid]
    )

    inserted_objects = []
    committed = []

    mock_session = AsyncMock()

    # db.add() is called synchronously in the CLI script
    def fake_add(obj):
        inserted_objects.append(obj)

    async def fake_commit():
        committed.append(True)

    mock_session.add = fake_add
    mock_session.commit = fake_commit

    if "obsidian_vault_export" in sys.modules:
        del sys.modules["obsidian_vault_export"]

    with patch("src.models.database.AsyncSessionLocal") as factory:
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        try:
            import obsidian_vault_export as cli  # type: ignore[import]

            cli.main()
        except SystemExit as e:
            assert e.code == 0 or e.code is None

    assert committed, "Session was not committed"
    assert len(inserted_objects) == 1

    row = inserted_objects[0]
    assert row.dag_id == "obsidian_vault_export"
    assert row.status == "pending"
    assert row.payload == {}
    captured = capsys.readouterr()
    assert str(row.id) in captured.out


# ---------------------------------------------------------------------------
# C5 — No HTTP surface
# ---------------------------------------------------------------------------


def test_c5_no_http_route_for_obsidian_vault_export():
    """TC-C05: No API route exposes obsidian_vault_export (CLI-only per requirement)."""
    from src.main import app

    route_paths = [str(route.path) for route in app.routes if hasattr(route, "path")]
    for path in route_paths:
        assert "obsidian_vault_export" not in path, (
            f"Route '{path}' exposes obsidian_vault_export — this is out of scope for FEAT-166 (CLI-only)"
        )
