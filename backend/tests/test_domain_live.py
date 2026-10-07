"""Finance / Stocks KPIs come from real integration snapshots, not seeded rows."""

from src.services import domain_live as d


def test_finance_kpis_empty_without_accounts():
    assert d.build_finance_kpis(None) == []
    assert d.build_finance_kpis({"accounts": []}) == []


def test_finance_kpis_assets_and_liabilities_by_currency():
    cfg = {
        "account_count": 3,
        "accounts": [
            {"type": "depository", "balance": 1000.4, "currency": "USD"},
            {"type": "investment", "balance": 500, "currency": "USD"},
            {"type": "credit", "balance": 200, "currency": "USD"},
        ],
    }
    out = {k["label"]: k for k in d.build_finance_kpis(cfg)}
    assert out["Linked accounts"]["value"] == "3"
    assert out["Cash & investments"]["value"] == "USD 1,500"
    assert out["Credit & loans owed"]["value"] == "USD 200"
    assert out["Cash & investments"].get("delta") is None


def test_finance_kpis_mixed_currencies_and_partial_flag():
    cfg = {
        "account_count": 12,
        "accounts": [
            {"type": "depository", "balance": 100, "currency": "USD"},
            {"type": "depository", "balance": 50, "currency": "EUR"},
        ],
    }
    out = {k["label"]: k for k in d.build_finance_kpis(cfg)}
    assert out["Cash & investments"]["value"] == "EUR 50 + USD 100"
    assert out["Cash & investments"]["delta"] == "first 10 accounts only"


def test_finance_skips_accounts_without_numeric_balance():
    cfg = {"accounts": [{"type": "depository", "balance": None, "currency": "USD"}]}
    out = d.build_finance_kpis(cfg)
    assert [k["label"] for k in out] == ["Linked accounts"]


def test_stocks_kpis_empty_without_holdings():
    assert d.build_stocks_kpis([None, {}]) == []


def test_stocks_kpis_value_and_pnl_across_brokers():
    kite = {
        "holding_count": 2,
        "holdings": [
            {"qty": 10, "ltp": 100, "pnl": 50},
            {"qty": 5, "ltp": 200, "pnl": -20},
        ],
    }
    upstox = {"holding_count": 1, "holdings": [{"qty": 2, "ltp": 50}]}
    out = {k["label"]: k for k in d.build_stocks_kpis([kite, upstox])}
    assert out["Holdings"]["value"] == "3"
    assert out["Market value"]["value"] == "₹2,100"
    assert out["Unrealised P&L"]["value"] == "+₹30"
    assert out["Market value"].get("delta") is None


def test_stocks_kpis_flag_partial_when_more_holdings_than_stored():
    cfg = {"holding_count": 40, "holdings": [{"qty": 1, "ltp": 10, "pnl": -5}]}
    out = {k["label"]: k for k in d.build_stocks_kpis([cfg])}
    assert out["Holdings"]["value"] == "40"
    assert out["Unrealised P&L"]["value"] == "-₹5"
    assert out["Market value"]["delta"] == "top 10 holdings per broker"
