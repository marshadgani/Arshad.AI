"""Route-level checks: every per-user query is bound to the caller, and the
domain endpoint serves live KPIs or nothing."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from src.api.v1 import dashboard, domains

NOW = datetime.now(timezone.utc)
USER = SimpleNamespace(id=uuid.uuid4())
OTHER = uuid.uuid4()


class Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class CapturingDB:
    """Records each statement and returns canned rows in order."""

    def __init__(self, *results):
        self.results = list(results)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return Result(self.results.pop(0) if self.results else [])

    def sql(self, index=0):
        return str(self.statements[index].compile())

    def bound(self, index=0):
        return list(self.statements[index].compile().params.values())


def gh(kind, number, title, state="open"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind=kind,
        provider_id=f"me/app#{number}",
        occurred_at=NOW - timedelta(hours=5),
        raw={"title": title, "state": state},
    )


def run(coro):
    return asyncio.run(coro)


def test_tasks_query_is_scoped_to_user_and_open_state():
    db = CapturingDB([gh("pr", 1, "fix")])
    out = run(dashboard.list_tasks(USER, db))
    assert out["total"] == 1 and out["data"][0]["source"] == "github"
    assert "user_id" in db.sql()
    assert USER.id in db.bound()
    assert "open" in db.bound()


def test_decisions_and_focus_use_the_same_scoped_query():
    db = CapturingDB([gh("pr", 1, "fix")])
    decisions = run(dashboard.list_decisions(USER, db))
    assert decisions["data"][0]["waitingSince"].endswith("h")
    assert USER.id in db.bound()

    db2 = CapturingDB([gh("pr", 1, "fix")])
    focus = run(dashboard.get_focus(USER, db2))
    assert focus["data"]["title"] == "Review me/app#1 fix"
    assert USER.id in db2.bound()


def test_empty_user_gets_honest_empty_responses_not_seed_rows():
    assert run(dashboard.list_tasks(USER, CapturingDB([])))["data"] == []
    assert run(dashboard.list_decisions(USER, CapturingDB([])))["data"] == []
    focus = run(dashboard.get_focus(USER, CapturingDB([])))
    assert focus["data"]["title"] == "Nothing urgent"


def test_notifications_query_scoped_and_only_unhealthy_shown():
    bad = SimpleNamespace(
        id=1, slug="gmail", status="expired", last_error=None, last_synced_at=NOW
    )
    ok = SimpleNamespace(
        id=2, slug="github", status="connected", last_error=None, last_synced_at=NOW
    )
    db = CapturingDB([bad, ok])
    out = run(dashboard.list_notifications(USER, db))
    assert [n["severity"] for n in out["data"]] == ["warn"]
    assert "user_id" in db.sql() and USER.id in db.bound()


def test_agent_activity_is_attributed_through_the_users_chat_sessions():
    log = SimpleNamespace(
        id=uuid.uuid4(), agent_name="chat", success=True, invoked_at=NOW
    )
    db = CapturingDB([log])
    out = run(dashboard.list_agent_activity(USER, db))
    assert out["total"] == 1
    sql = db.sql()
    assert "conversation_sessions" in sql and "user_id" in sql
    assert USER.id in db.bound()
    assert OTHER not in db.bound()


def test_weather_invalid_stored_location_does_not_500():
    integration = SimpleNamespace(config={"latitude": "abc", "longitude": "xyz"})
    out = run(dashboard.get_weather(USER, CapturingDB([integration])))
    assert out["data"]["temp"] == "—"
    assert "invalid" in out["data"]["condition"]


def test_weather_integration_query_is_scoped():
    db = CapturingDB([])
    run(dashboard.get_weather(USER, db))
    assert USER.id in db.bound()
    assert "open_meteo" in db.bound()


# ── domains ─────────────────────────────────────────────────────────


def domain_obj(slug):
    return SimpleNamespace(
        slug=slug,
        title=slug.title(),
        emoji="x",
        tagline="t",
        kpis=[SimpleNamespace(label="Fake", value="₹1.42 Cr", delta=None)],
        applications=[
            SimpleNamespace(id="a", name="App", description="d", status="live")
        ],
        agents=[
            SimpleNamespace(
                name="n",
                description="d",
                health="healthy",
                uptime="99%",
                accuracy=94,
                last_action="x",
                last_run="1m",
            )
        ],
        feed=[SimpleNamespace(id="f", message="fake", time="1m")],
    )


def get_domain(slug, *results):
    db = CapturingDB(*results)
    return run(domains.get_domain(slug, USER, db)), db


@pytest.mark.parametrize("slug", ["travel", "home", "learning"])
def test_coming_soon_domains_serve_nothing_fabricated(slug):
    out, _ = get_domain(slug, [domain_obj(slug)], [])
    data = out["data"]
    assert data["status"] == "coming_soon"
    assert data["applications"] == [] and data["kpis"] == []
    assert data["agents"] == [] and data["feed"] == []


def test_finance_serves_live_plaid_kpis_and_no_seeded_telemetry():
    plaid = SimpleNamespace(
        config={
            "account_count": 1,
            "accounts": [{"type": "depository", "balance": 900, "currency": "USD"}],
        }
    )
    out, db = get_domain("finance", [domain_obj("finance")], [plaid])
    data = out["data"]
    assert data["status"] == "live"
    assert [k["label"] for k in data["kpis"]] == [
        "Linked accounts",
        "Cash & investments",
    ]
    assert "Fake" not in str(data["kpis"])
    assert data["agents"] == [] and data["feed"] == []
    assert len(data["applications"]) == 1
    assert USER.id in db.bound(1) and ["plaid"] in db.bound(1)


def test_finance_without_plaid_has_no_kpis_at_all():
    out, _ = get_domain("finance", [domain_obj("finance")], [])
    assert out["data"]["kpis"] == []


def test_stocks_combines_both_brokers():
    kite = SimpleNamespace(
        config={"holding_count": 1, "holdings": [{"qty": 2, "ltp": 100, "pnl": 10}]}
    )
    upstox = SimpleNamespace(
        config={"holding_count": 1, "holdings": [{"qty": 1, "ltp": 50}]}
    )
    out, db = get_domain("stocks", [domain_obj("stocks")], [kite, upstox])
    kpis = {k["label"]: k["value"] for k in out["data"]["kpis"]}
    assert kpis["Holdings"] == "2" and kpis["Market value"] == "₹250"
    assert "zerodha_kite" in db.bound(1) or "zerodha_kite" in str(db.bound(1))


def test_other_domains_get_no_fabricated_kpis():
    out, _ = get_domain("shopify", [domain_obj("shopify")])
    assert out["data"]["kpis"] == []


def test_unknown_domain_is_404():
    with pytest.raises(HTTPException) as exc:
        get_domain("nope", [])
    assert exc.value.status_code == 404
