"""Unit tests for runner.py dispatch of obsidian_vault_export.

Linked requirements: REQ-007.
"""

from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# D1 — runner dispatches new dag_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d1_runner_dispatches_obsidian_vault_export():
    """TC-D01: run(dag_id='obsidian_vault_export') calls export() and returns its result."""
    expected_result = {
        "status": "completed",
        "files_exported": 1,
        "commit_sha": "abc123",
    }
    mock_export = AsyncMock(return_value=expected_result)

    mock_db = AsyncMock()
    user_id = uuid.uuid4()
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_db.scalar = AsyncMock(return_value=mock_user)

    from src.services.ingestion import runner

    with patch("src.services.ingestion.obsidian_vault_export.export", mock_export):
        result = await runner.run(
            dag_id="obsidian_vault_export",
            user_id=user_id,
            payload={},
            db=mock_db,
        )

    mock_export.assert_awaited_once()
    assert result == expected_result


# ---------------------------------------------------------------------------
# D2 — existing dispatch unaffected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d2_existing_dispatch_unaffected():
    """TC-D02: unknown dag_id still raises IngestionError."""
    from src.services.ingestion.errors import IngestionError

    mock_db = AsyncMock()
    user_id = uuid.uuid4()
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_db.scalar = AsyncMock(return_value=mock_user)

    from src.services.ingestion import runner

    with pytest.raises(IngestionError, match="unknown_dag_id"):
        await runner.run(
            dag_id="totally_unknown_dag_xyz",
            user_id=user_id,
            payload={},
            db=mock_db,
        )


# ---------------------------------------------------------------------------
# D3 — lazy import
# ---------------------------------------------------------------------------


def test_d3_lazy_import_of_vault_export():
    """TC-D03: Importing runner does not import obsidian_vault_export or obsidian_vault_git."""
    for key in list(sys.modules.keys()):
        if "obsidian_vault_export" in key or "obsidian_vault_git" in key:
            del sys.modules[key]
    if "src.services.ingestion.runner" in sys.modules:
        del sys.modules["src.services.ingestion.runner"]

    import src.services.ingestion.runner  # noqa: F401

    assert "src.services.ingestion.obsidian_vault_export" not in sys.modules, (
        "Importing runner eagerly imported obsidian_vault_export — "
        "missing git binary or missing env var can break all other dispatches"
    )
    assert "src.services.ingestion.obsidian_vault_git" not in sys.modules, (
        "Importing runner eagerly imported obsidian_vault_git"
    )
