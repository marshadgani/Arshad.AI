"""Runner dispatch and CLI trigger tests for obsidian_vault_export."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.services.ingestion import runner
from src.services.ingestion.errors import IngestionError

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


@pytest.mark.asyncio
async def test_runner_dispatches_to_export_with_user_and_payload():
    user = MagicMock(id=uuid.uuid4())
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=user)
    with patch(
        "src.services.ingestion.obsidian_vault_export.export",
        AsyncMock(return_value={"status": "ok"}),
    ) as exp:
        out = await runner.run(
            dag_id="obsidian_vault_export", user_id=user.id, payload={"a": 1}, db=db
        )
    assert out == {"status": "ok"}
    exp.assert_awaited_once_with(user=user, db=db, payload={"a": 1})


@pytest.mark.asyncio
async def test_runner_unknown_dag_and_missing_user_still_raise():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    with pytest.raises(IngestionError, match="unknown_dag_id"):
        await runner.run(dag_id="nope", user_id=uuid.uuid4(), payload={}, db=db)
    db.scalar = AsyncMock(return_value=None)
    with pytest.raises(IngestionError, match="user_not_found"):
        await runner.run(
            dag_id="obsidian_vault_export", user_id=uuid.uuid4(), payload={}, db=db
        )


def _session():
    s = AsyncMock()
    s.add = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=s)
    cm.__aexit__ = AsyncMock(return_value=False)
    return s, MagicMock(return_value=cm)


def _cli(monkeypatch, argv, factory):
    import obsidian_vault_export as cli

    monkeypatch.setattr(cli, "AsyncSessionLocal", factory)
    monkeypatch.setattr(sys, "argv", ["obsidian_vault_export.py", *argv])
    return cli


def test_cli_inserts_pending_row_with_empty_payload_and_prints_id(monkeypatch, capsys):
    uid = uuid.uuid4()
    s, factory = _session()
    _cli(monkeypatch, ["--user-id", str(uid)], factory).main()
    row = s.add.call_args.args[0]
    assert (row.dag_id, row.status, row.payload, row.user_id) == (
        "obsidian_vault_export",
        "pending",
        {},
        uid,
    )
    s.commit.assert_awaited_once()
    assert str(row.id) in capsys.readouterr().out


def test_cli_arg_beats_env(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_EXPORT_USER_ID", str(uuid.uuid4()))
    uid = uuid.uuid4()
    s, factory = _session()
    _cli(monkeypatch, ["--user-id", str(uid)], factory).main()
    assert s.add.call_args.args[0].user_id == uid


def test_cli_env_used_when_no_arg(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setenv("OBSIDIAN_VAULT_EXPORT_USER_ID", str(uid))
    s, factory = _session()
    _cli(monkeypatch, [], factory).main()
    assert s.add.call_args.args[0].user_id == uid


@pytest.mark.parametrize("rows", [[], [(uuid.uuid4(), "a@x"), (uuid.uuid4(), "b@x")]])
def test_cli_zero_or_many_users_exits_2_and_inserts_nothing(monkeypatch, rows):
    monkeypatch.delenv("OBSIDIAN_VAULT_EXPORT_USER_ID", raising=False)
    s, factory = _session()
    s.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, [], factory).main()
    assert e.value.code == 2
    s.add.assert_not_called()


def test_cli_single_user_auto_selected(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_EXPORT_USER_ID", raising=False)
    uid = uuid.uuid4()
    s, factory = _session()
    s.execute = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[(uid, "a@x")]))
    )
    _cli(monkeypatch, [], factory).main()
    assert s.add.call_args.args[0].user_id == uid


def test_cli_invalid_uuid_fails_without_insert(monkeypatch):
    s, factory = _session()
    with pytest.raises(SystemExit) as exc:
        _cli(monkeypatch, ["--user-id", "nope"], factory).main()
    assert exc.value.code != 0
    s.add.assert_not_called()


def test_no_http_route_exposes_vault_export():
    from src.main import app

    assert not [
        r.path
        for r in app.routes
        if "vault" in getattr(r, "path", "") and "export" in r.path
    ]
