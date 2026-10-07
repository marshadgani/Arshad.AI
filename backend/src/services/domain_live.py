"""Live KPIs for the Finance and Stock Market domain pages.

Reads the account / holdings snapshots that the Plaid, Zerodha Kite and
Upstox integrations already store in ``Integration.config`` on every sync.
Pure transforms so they are unit-testable without a database.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

_ASSET_TYPES = {"depository", "investment"}
_LIABILITY_TYPES = {"credit", "loan"}
_STORED_LIMIT = 10  # integrations persist at most this many accounts / holdings


def _money(by_currency: dict[str, float]) -> str:
    return " + ".join(
        f"{cur} {amount:,.0f}" for cur, amount in sorted(by_currency.items())
    )


def build_finance_kpis(plaid_config: dict[str, Any] | None) -> list[dict[str, str]]:
    cfg = plaid_config or {}
    accounts = cfg.get("accounts") or []
    if not accounts:
        return []

    assets: dict[str, float] = defaultdict(float)
    owed: dict[str, float] = defaultdict(float)
    for a in accounts:
        balance = a.get("balance")
        if not isinstance(balance, (int, float)):
            continue
        currency = a.get("currency") or "?"
        if a.get("type") in _ASSET_TYPES:
            assets[currency] += balance
        elif a.get("type") in _LIABILITY_TYPES:
            owed[currency] += balance

    total = int(cfg.get("account_count") or len(accounts))
    partial = "first 10 accounts only" if total > _STORED_LIMIT else None
    kpis = [{"label": "Linked accounts", "value": str(total)}]
    if assets:
        kpis.append(
            {"label": "Cash & investments", "value": _money(assets), "delta": partial}
        )
    if owed:
        kpis.append(
            {"label": "Credit & loans owed", "value": _money(owed), "delta": partial}
        )
    return kpis


def build_stocks_kpis(
    broker_configs: Iterable[dict[str, Any] | None],
) -> list[dict[str, str]]:
    configs = [c for c in broker_configs if c and c.get("holdings") is not None]
    if not configs:
        return []

    count = sum(int(c.get("holding_count") or len(c["holdings"])) for c in configs)
    stored = [h for c in configs for h in c["holdings"]]
    partial = "top 10 holdings per broker" if count > len(stored) else None

    value = sum(
        h["qty"] * h["ltp"]
        for h in stored
        if isinstance(h.get("qty"), (int, float))
        and isinstance(h.get("ltp"), (int, float))
    )
    pnls = [h["pnl"] for h in stored if isinstance(h.get("pnl"), (int, float))]

    kpis = [{"label": "Holdings", "value": str(count)}]
    if value:
        kpis.append(
            {"label": "Market value", "value": f"₹{value:,.0f}", "delta": partial}
        )
    if pnls:
        pnl = sum(pnls)
        kpis.append(
            {
                "label": "Unrealised P&L",
                "value": f"{'+' if pnl >= 0 else '-'}₹{abs(pnl):,.0f}",
                "delta": partial,
            }
        )
    return kpis
