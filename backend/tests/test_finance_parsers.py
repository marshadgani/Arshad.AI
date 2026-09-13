"""Unit tests for services/finance/parsers.py.

Pure-function tests — no DB, no HTTP, no fixtures beyond plain dicts.
Covers to_float, iso_utc, as_config, resolve_holding_count, and
parse_holdings (including bool/NaN/inf rejection, string coercion,
pnl passthrough, and malformed-row skipping).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from src.services.finance.parsers import (
    as_config,
    iso_utc,
    parse_holdings,
    resolve_holding_count,
    to_float,
)

# ── to_float ──────────────────────────────────────────────────────────────────


class TestToFloat:
    def test_int_becomes_float(self):
        assert to_float(42) == 42.0

    def test_float_passthrough(self):
        assert to_float(3.14) == pytest.approx(3.14)

    def test_string_numeric(self):
        assert to_float("12.5") == pytest.approx(12.5)

    def test_string_with_whitespace(self):
        assert to_float("  7.0  ") == pytest.approx(7.0)

    def test_non_numeric_string_returns_none(self):
        assert to_float("abc") is None

    def test_none_returns_none(self):
        assert to_float(None) is None

    def test_bool_true_rejected(self):
        # bool is a subclass of int in Python — must not become 1.0
        assert to_float(True) is None

    def test_bool_false_rejected(self):
        assert to_float(False) is None

    def test_nan_rejected(self):
        assert to_float(float("nan")) is None

    def test_inf_rejected(self):
        assert to_float(float("inf")) is None

    def test_neg_inf_rejected(self):
        assert to_float(float("-inf")) is None

    def test_list_returns_none(self):
        assert to_float([1, 2]) is None

    def test_dict_returns_none(self):
        assert to_float({"v": 1}) is None

    def test_zero_passthrough(self):
        assert to_float(0) == 0.0

    def test_negative_float(self):
        assert to_float(-5.5) == pytest.approx(-5.5)


# ── iso_utc ───────────────────────────────────────────────────────────────────


class TestIsoUtc:
    def test_none_returns_none(self):
        assert iso_utc(None) is None

    def test_aware_datetime_includes_offset(self):
        dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = iso_utc(dt)
        assert result is not None
        assert "+00:00" in result or result.endswith("Z")

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 1, 15, 12, 0, 0)  # naive
        result = iso_utc(dt)
        assert result is not None
        # Must include the UTC offset to avoid browser local-time interpretation
        assert "+00:00" in result or result.endswith("Z")

    def test_round_trip(self):
        dt = datetime(2026, 6, 1, 9, 30, 0, tzinfo=timezone.utc)
        result = iso_utc(dt)
        parsed = datetime.fromisoformat(result)  # type: ignore[arg-type]
        assert parsed == dt


# ── as_config ─────────────────────────────────────────────────────────────────


class TestAsConfig:
    def test_dict_passthrough(self):
        d = {"holdings": [], "holding_count": 3}
        assert as_config(d) is d

    def test_none_returns_empty_dict(self):
        assert as_config(None) == {}

    def test_non_dict_returns_empty_dict(self, caplog):
        result = as_config(["not", "a", "dict"], slug="upstox")
        assert result == {}
        assert "upstox" in caplog.text

    def test_non_dict_logs_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            as_config(42, slug="zerodha_kite")
        assert "zerodha_kite" in caplog.text


# ── resolve_holding_count ─────────────────────────────────────────────────────


class TestResolveHoldingCount:
    def test_stored_count_used_when_higher(self):
        config = {"holding_count": 50}
        assert resolve_holding_count(config, shown=10) == 50

    def test_shown_count_used_when_higher(self):
        # stored=3, shown=10 — must not understate what is on screen
        config = {"holding_count": 3}
        assert resolve_holding_count(config, shown=10) == 10

    def test_missing_holding_count_falls_back_to_shown(self):
        assert resolve_holding_count({}, shown=7) == 7

    def test_null_holding_count_falls_back_to_shown(self):
        assert resolve_holding_count({"holding_count": None}, shown=5) == 5

    def test_unparseable_holding_count_falls_back(self, caplog):
        result = resolve_holding_count({"holding_count": "bad"}, shown=4, slug="upstox")
        assert result == 4
        assert "upstox" in caplog.text

    def test_string_numeric_holding_count(self):
        # Kite has historically returned some numerics as strings
        result = resolve_holding_count({"holding_count": "15"}, shown=10)
        assert result == 15

    def test_zero_stored_uses_shown(self):
        result = resolve_holding_count({"holding_count": 0}, shown=5)
        assert result == 5


# ── parse_holdings ────────────────────────────────────────────────────────────


class TestParseHoldings:
    def _config(self, holdings: list) -> dict:
        return {"holdings": holdings}

    def test_happy_path_all_four_fields(self):
        row = {"symbol": "RELIANCE", "qty": 10, "ltp": 2500.0, "pnl": 500.0}
        result = parse_holdings(self._config([row]))
        assert len(result) == 1
        h = result[0]
        assert h.symbol == "RELIANCE"
        assert h.qty == pytest.approx(10.0)
        assert h.ltp == pytest.approx(2500.0)
        assert h.pnl == pytest.approx(500.0)

    def test_value_computed_server_side(self):
        row = {"symbol": "TCS", "qty": 5, "ltp": 4000.0, "pnl": None}
        result = parse_holdings(self._config([row]))
        assert result[0].value == pytest.approx(20000.0)

    def test_value_none_when_qty_missing(self):
        row = {"symbol": "INFY", "qty": None, "ltp": 1800.0}
        result = parse_holdings(self._config([row]))
        assert result[0].value is None

    def test_value_none_when_ltp_missing(self):
        row = {"symbol": "HDFC", "qty": 3, "ltp": None}
        result = parse_holdings(self._config([row]))
        assert result[0].value is None

    def test_pnl_passthrough(self):
        row = {"symbol": "WIPRO", "qty": 2, "ltp": 500.0, "pnl": -100.5}
        result = parse_holdings(self._config([row]))
        assert result[0].pnl == pytest.approx(-100.5)

    def test_pnl_none_when_absent(self):
        row = {"symbol": "HCL", "qty": 2, "ltp": 1200.0}
        result = parse_holdings(self._config([row]))
        assert result[0].pnl is None

    def test_missing_symbol_row_skipped(self, caplog):
        rows = [{"qty": 1, "ltp": 100.0}, {"symbol": "VALID", "qty": 1, "ltp": 100.0}]
        result = parse_holdings(self._config(rows))
        assert len(result) == 1
        assert result[0].symbol == "VALID"

    def test_empty_symbol_row_skipped(self):
        rows = [{"symbol": "  ", "qty": 1}, {"symbol": "OK", "qty": 1, "ltp": 50.0}]
        result = parse_holdings(self._config(rows))
        assert len(result) == 1

    def test_non_dict_row_skipped(self):
        rows = ["bad_row", {"symbol": "GOOD", "qty": 1, "ltp": 50.0}]
        result = parse_holdings(self._config(rows))
        assert len(result) == 1

    def test_null_holdings_key_returns_empty(self):
        assert parse_holdings({"holdings": None}) == []

    def test_missing_holdings_key_returns_empty(self):
        assert parse_holdings({}) == []

    def test_non_list_holdings_returns_empty(self, caplog):
        result = parse_holdings({"holdings": {"bad": True}}, slug="upstox")
        assert result == []
        assert "upstox" in caplog.text

    def test_bool_qty_rejected(self):
        row = {"symbol": "TEST", "qty": True, "ltp": 100.0}
        result = parse_holdings(self._config([row]))
        assert result[0].qty is None

    def test_string_numeric_ltp(self):
        row = {"symbol": "KITE", "qty": 1, "ltp": "999.5"}
        result = parse_holdings(self._config([row]))
        assert result[0].ltp == pytest.approx(999.5)

    def test_inf_ltp_rejected(self):
        row = {"symbol": "BAD", "qty": 1, "ltp": float("inf")}
        result = parse_holdings(self._config([row]))
        assert result[0].ltp is None
        assert result[0].value is None
