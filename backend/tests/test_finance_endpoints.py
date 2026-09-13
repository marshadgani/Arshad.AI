"""Tests for GET /api/v1/finance/holdings.

Monkeypatches src.api.v1.finance.state.find_integration and uses lightweight
Integration-shaped stubs -- no DB fixture needed. Per
.claude/rules/subagent-verification.md, verify collaborator paths directly
rather than trusting an unverified import.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
import src.api.v1.finance as finance_module
from httpx import ASGITransport, AsyncClient
from src.main import app


def _integration(
    *,
    slug: str,
    status: str = "connected",
    config: dict | None = None,
    last_synced_at: datetime | None = None,
    last_error: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        slug=slug,
        status=status,
        config=config if config is not None else {},
        last_synced_at=last_synced_at,
        last_error=last_error,
    )


@pytest.fixture(autouse=True)
def _fake_user(monkeypatch):
    fake_user = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")

    async def _get_current_user():
        return fake_user

    from src.auth.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = _get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(finance_module, "_check_rate_limit", _noop)


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_no_integrations_returns_disconnected(monkeypatch):
    async def _find(user_id, slug, db):
        return None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["connected"] is False
    assert body["data"]["brokers"] == []


@pytest.mark.asyncio
async def test_upstox_only_connected(monkeypatch):
    upstox = _integration(
        slug="upstox",
        config={
            "holding_count": 2,
            "holdings": [
                {"symbol": "TCS", "qty": 10, "ltp": 3500.5},
                {"symbol": "INFY", "qty": 5, "ltp": 1500.0},
            ],
        },
        last_synced_at=datetime(2026, 9, 12, 9, 30),
    )

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    body = resp.json()["data"]
    assert body["connected"] is True
    assert len(body["brokers"]) == 1
    broker = body["brokers"][0]
    assert broker["broker"] == "upstox"
    assert broker["holdings"][0]["symbol"] == "TCS"
    assert broker["holdings"][0]["pnl"] is None
    assert broker["holdings"][0]["value"] == pytest.approx(35005.0)
    assert broker["last_synced_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_zerodha_only_has_pnl(monkeypatch):
    zerodha = _integration(
        slug="zerodha_kite",
        config={
            "holding_count": 1,
            "holdings": [{"symbol": "RELIANCE", "qty": 2, "ltp": 2400.0, "pnl": 100.0}],
        },
    )

    async def _find(user_id, slug, db):
        return zerodha if slug == "zerodha_kite" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    broker = resp.json()["data"]["brokers"][0]
    assert broker["holdings"][0]["pnl"] == 100.0


@pytest.mark.asyncio
async def test_both_brokers_connected_returns_two_entries_in_order(monkeypatch):
    upstox = _integration(slug="upstox", config={"holdings": []})
    zerodha = _integration(slug="zerodha_kite", config={"holdings": []})

    async def _find(user_id, slug, db):
        return {"upstox": upstox, "zerodha_kite": zerodha}[slug]

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    brokers = resp.json()["data"]["brokers"]
    assert [b["broker"] for b in brokers] == ["upstox", "zerodha_kite"]


@pytest.mark.asyncio
async def test_expired_status_sets_needs_reauth(monkeypatch):
    upstox = _integration(slug="upstox", status="expired", config={})

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == 200
    broker = resp.json()["data"]["brokers"][0]
    assert broker["needs_reauth"] is True
    assert broker["status"] == "expired"


@pytest.mark.asyncio
async def test_empty_config_returns_no_holdings(monkeypatch):
    upstox = _integration(slug="upstox", config={})

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    broker = resp.json()["data"]["brokers"][0]
    assert broker["holdings"] == []
    assert broker["holding_count"] == 0
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_null_holdings_value_returns_empty_list(monkeypatch):
    upstox = _integration(slug="upstox", config={"holdings": None})

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["brokers"][0]["holdings"] == []


@pytest.mark.asyncio
async def test_non_list_holdings_value_returns_empty_list(monkeypatch):
    upstox = _integration(slug="upstox", config={"holdings": "nope"})

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.json()["data"]["brokers"][0]["holdings"] == []


@pytest.mark.asyncio
async def test_row_missing_symbol_is_skipped(monkeypatch):
    upstox = _integration(
        slug="upstox",
        config={
            "holdings": [{"qty": 1, "ltp": 2}, {"symbol": "TCS", "qty": 1, "ltp": 2}]
        },
    )

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    holdings = resp.json()["data"]["brokers"][0]["holdings"]
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "TCS"


@pytest.mark.asyncio
async def test_null_qty_yields_null_value(monkeypatch):
    upstox = _integration(
        slug="upstox",
        config={"holdings": [{"symbol": "TCS", "qty": None, "ltp": "123.5"}]},
    )

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    holding = resp.json()["data"]["brokers"][0]["holdings"][0]
    assert holding["qty"] is None
    assert holding["ltp"] == 123.5
    assert holding["value"] is None


@pytest.mark.asyncio
async def test_truncated_flag_set_when_count_exceeds_rows(monkeypatch):
    upstox = _integration(
        slug="upstox",
        config={
            "holding_count": 42,
            "holdings": [{"symbol": f"S{i}", "qty": 1, "ltp": 1} for i in range(10)],
        },
    )

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    broker = resp.json()["data"]["brokers"][0]
    assert broker["truncated"] is True
    assert broker["holding_count"] == 42


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(monkeypatch):
    async def _rate_limited(user_id: str) -> None:
        from src.api.errors import http_error

        raise http_error(429, "rate_limit_exceeded", "Too many requests.")

    monkeypatch.setattr(finance_module, "_check_rate_limit", _rate_limited)

    async def _find(user_id, slug, db):
        return None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_no_auth_header_returns_401():
    app.dependency_overrides.clear()

    async with await _client() as client:
        resp = await client.get("/api/v1/finance/holdings")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_status_returns_human_safe_reconnect_message(monkeypatch):
    zerodha = _integration(slug="zerodha_kite", status="expired", config={})

    async def _find(user_id, slug, db):
        return zerodha if slug == "zerodha_kite" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    broker = resp.json()["data"]["brokers"][0]
    assert broker["needs_reauth"] is True
    assert broker["error"] is not None
    assert "reconnect" in broker["error"].lower()


@pytest.mark.asyncio
async def test_error_status_never_leaks_raw_exception_text(monkeypatch):
    """WP-2 regression guard: BrokerHoldings.error must never contain a raw
    exception class name, status code text, or upstream URL — even when
    Integration.last_error holds exactly that."""
    upstox = _integration(
        slug="upstox",
        status="error",
        last_error=(
            "HTTPStatusError: Client error 401 for url "
            "https://api.upstox.com/v2/portfolio/long-term-holdings"
        ),
        config={},
    )

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    broker = resp.json()["data"]["brokers"][0]
    assert broker["error"] is not None
    assert broker["error"] != ""
    lowered = broker["error"].lower()
    assert "httpstatuserror" not in lowered
    assert "http" not in lowered
    assert "upstox.com" not in lowered


@pytest.mark.asyncio
async def test_connected_status_has_no_error_message(monkeypatch):
    upstox = _integration(slug="upstox", status="connected", config={})

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.json()["data"]["brokers"][0]["error"] is None


@pytest.mark.asyncio
async def test_lookup_failure_card_carries_a_user_facing_message(monkeypatch):
    """A DB failure on one broker's lookup degrades that card to status=error.
    It must still say something: an error card with error=None rendered as a
    bare "No holdings to display", indistinguishable to the user from a
    genuinely empty portfolio.
    """
    from sqlalchemy.exc import OperationalError

    async def _find(user_id, slug, db):
        if slug == "upstox":
            raise OperationalError("SELECT 1", {}, Exception("connection lost"))
        return None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == 200
    card = resp.json()["data"]["brokers"][0]
    assert card["broker"] == "upstox"
    assert card["status"] == "error"
    assert card["error"]
    # Still no internal detail on the wire.
    lowered = card["error"].lower()
    assert "operationalerror" not in lowered
    assert "select" not in lowered


@pytest.mark.asyncio
async def test_one_broker_lookup_failure_does_not_take_down_a_healthy_broker(
    monkeypatch,
):
    """Isolation guard: per services/finance/holdings.py's collect_broker_holdings
    docstring, each broker's lookup is isolated so a DB failure on one slug
    degrades only that card -- it must never blank out or otherwise corrupt a
    sibling broker that looked up and rendered successfully. This is the core
    resilience property of the always-200 endpoint and was previously only
    exercised with the healthy slug returning no row at all, which cannot
    distinguish "isolated" from "the whole response happened to survive
    because there was nothing else to break".
    """
    from sqlalchemy.exc import OperationalError

    zerodha = _integration(
        slug="zerodha_kite",
        config={
            "holding_count": 1,
            "holdings": [{"symbol": "RELIANCE", "qty": 2, "ltp": 2400.0, "pnl": 10.0}],
        },
    )

    async def _find(user_id, slug, db):
        if slug == "upstox":
            raise OperationalError("SELECT 1", {}, Exception("connection lost"))
        return zerodha

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is True
    brokers_by_slug = {b["broker"]: b for b in body["brokers"]}

    assert brokers_by_slug["upstox"]["status"] == "error"
    assert brokers_by_slug["upstox"]["holdings"] == []

    healthy = brokers_by_slug["zerodha_kite"]
    assert healthy["status"] == "connected"
    assert healthy["error"] is None
    assert healthy["holdings"][0]["symbol"] == "RELIANCE"
    assert healthy["holdings"][0]["pnl"] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_unexpected_integration_status_coerces_to_error(monkeypatch):
    """resolve_status() in services/finance/holdings.py must coerce any
    Integration.status value outside {"connected","expired","error"} to
    "error" rather than letting Pydantic reject it -- which would violate
    this endpoint's always-200 contract. This exercises DB drift (a legacy
    or externally-written status this feature doesn't recognise), which no
    existing test reaches because every other test uses one of the three
    known-good literal values.
    """
    upstox = _integration(slug="upstox", status="pending_verification", config={})

    async def _find(user_id, slug, db):
        return upstox if slug == "upstox" else None

    monkeypatch.setattr(finance_module.state, "find_integration", _find)

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/finance/holdings", headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == 200
    broker = resp.json()["data"]["brokers"][0]
    assert broker["status"] == "error"
    assert broker["needs_reauth"] is False
    assert broker["error"] is not None
