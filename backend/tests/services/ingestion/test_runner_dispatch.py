"""TC-051 through TC-055 — runner.run() dispatch and finalize_sync integration.

REQUIREMENTS COVERED:
  REQ-T51  Successful dispatch calls finalize_sync with success=True
  REQ-T52  Failed dispatch calls finalize_sync with success=False and error_text
  REQ-T53  finalize_sync is called even when _dispatch raises (try/except/else)
  REQ-T54  Unknown dag_id raises IngestionError (not a silent no-op)
  REQ-T55  user_not_found raises IngestionError before dispatch is attempted

Patch target note: runner.run() does `from .sync_completion import finalize_sync`
INSIDE the function body (a deliberate lazy import — see runner.py), so
`src.services.ingestion.runner` never carries `finalize_sync` as a
module-level attribute. `patch.object(runner, "finalize_sync", ...)`
therefore raises AttributeError before a single assertion runs (verified:
this was reproduced against the real module). The fix is the same as
dag_sync.py's: patch the name at its actual source,
`src.services.ingestion.sync_completion.finalize_sync`.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.services.ingestion.runner import IngestionError

FINALIZE_TARGET = "src.services.ingestion.sync_completion.finalize_sync"


def _fake_user(user_id: uuid.UUID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.email = "test@example.com"
    return u


@pytest.mark.asyncio
async def test_runner_calls_finalize_sync_with_success_true_on_success():
    """TC-051 — A successful ingest calls finalize_sync(success=True, error_text=None)."""
    from src.services.ingestion import runner

    user_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_fake_user(user_id))

    with patch(FINALIZE_TARGET, new_callable=AsyncMock) as mock_finalize:
        with patch(
            "src.services.ingestion.calendar.ingest",
            AsyncMock(return_value={"rows": 5}),
        ):
            result = await runner.run(
                dag_id="calendar_ingestor",
                user_id=user_id,
                payload={},
                db=db,
            )

    assert result == {"rows": 5}
    mock_finalize.assert_awaited_once_with(
        dag_id="calendar_ingestor", user_id=user_id, success=True, error_text=None
    )


@pytest.mark.asyncio
async def test_runner_calls_finalize_sync_with_success_false_and_error_text_on_failure():
    """TC-052 — A failing ingest calls finalize_sync(success=False, error_text=<exc summary>)
    and re-raises the original exception (TC-053: the wrapper never swallows it)."""
    from src.services.ingestion import runner

    user_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_fake_user(user_id))

    with patch(FINALIZE_TARGET, new_callable=AsyncMock) as mock_finalize:
        with patch(
            "src.services.ingestion.calendar.ingest",
            AsyncMock(side_effect=ValueError("upstream 429")),
        ):
            with pytest.raises(ValueError, match="upstream 429"):
                await runner.run(
                    dag_id="calendar_ingestor",
                    user_id=user_id,
                    payload={},
                    db=db,
                )

    mock_finalize.assert_awaited_once()
    _, kwargs = mock_finalize.call_args
    assert kwargs["success"] is False
    assert "ValueError" in kwargs["error_text"]
    assert "upstream 429" in kwargs["error_text"]


@pytest.mark.asyncio
async def test_runner_unknown_dag_id_raises_ingestion_error():
    """TC-054 — dag_id not in the dispatch table raises IngestionError, and
    finalize_sync is still called with success=False (the try/except/else
    wrapper covers _dispatch's own "unknown_dag_id" raise too)."""
    from src.services.ingestion import runner

    user_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_fake_user(user_id))

    with patch(FINALIZE_TARGET, new_callable=AsyncMock) as mock_finalize:
        with pytest.raises(IngestionError, match="unknown_dag_id"):
            await runner.run(
                dag_id="no_such_dag",
                user_id=user_id,
                payload={},
                db=db,
            )

    mock_finalize.assert_awaited_once()
    assert mock_finalize.call_args.kwargs["success"] is False


@pytest.mark.asyncio
async def test_runner_user_not_found_raises_before_dispatch():
    """TC-055 — When user_id has no DB row, IngestionError raised before any dispatch
    (and before finalize_sync — there is nothing to report bookkeeping for)."""
    from src.services.ingestion import runner

    user_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # user not found

    with patch(FINALIZE_TARGET, new_callable=AsyncMock) as mock_finalize:
        with pytest.raises(IngestionError, match="user_not_found"):
            await runner.run(
                dag_id="calendar_ingestor",
                user_id=user_id,
                payload={},
                db=db,
            )

    mock_finalize.assert_not_awaited()
