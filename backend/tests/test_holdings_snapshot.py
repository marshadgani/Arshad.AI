"""Direct unit tests for build_holdings_snapshot / make_holdings_parser.

Closes the gap identified in the FEAT-137 test-architect plan:
  - non-list `raw` values must not raise and must return empty snapshots
  - mixed valid/invalid (non-dict) rows in `raw` must be excluded before
    counting, so that `holding_count` reflects only renderable rows and the
    invariant  len(holdings) == min(holding_count, MAX_STORED_HOLDINGS)  holds

No I/O, no ORM, no DB fixture — inputs are plain Python objects.
"""

from __future__ import annotations

from src.integrations.personal._holdings_snapshot import (
    MAX_STORED_HOLDINGS,
    build_holdings_snapshot,
    make_holdings_parser,
)

# A field map that mirrors Upstox's real mapping (used across all tests so
# the shape is realistic rather than arbitrary).
FIELDS = {
    "symbol": "trading_symbol",
    "qty": "quantity",
    "ltp": "last_price",
    "pnl": "pnl",
}


class TestBuildHoldingsSnapshotNonListRaw:
    """Non-list inputs to `raw` must degrade to an empty snapshot, never raise."""

    def test_none_raw_produces_empty_snapshot(self):
        result = build_holdings_snapshot(None, fields=FIELDS)
        assert result["holding_count"] == 0
        assert result["holdings"] == []

    def test_dict_raw_produces_empty_snapshot(self):
        """A single dict (one holding without wrapping list) must not be iterated."""
        result = build_holdings_snapshot({"trading_symbol": "TCS"}, fields=FIELDS)
        assert result["holding_count"] == 0
        assert result["holdings"] == []

    def test_string_raw_produces_empty_snapshot(self):
        result = build_holdings_snapshot("garbage", fields=FIELDS)
        assert result["holding_count"] == 0
        assert result["holdings"] == []

    def test_integer_raw_produces_empty_snapshot(self):
        result = build_holdings_snapshot(42, fields=FIELDS)
        assert result["holding_count"] == 0
        assert result["holdings"] == []

    def test_empty_list_raw_produces_empty_snapshot(self):
        result = build_holdings_snapshot([], fields=FIELDS)
        assert result["holding_count"] == 0
        assert result["holdings"] == []


class TestBuildHoldingsSnapshotMixedRows:
    """Non-dict rows inside a list must be dropped before counting."""

    def test_non_dict_rows_excluded_from_holding_count(self):
        raw = [
            "string-row",
            42,
            None,
            {"trading_symbol": "TCS", "quantity": 1, "last_price": 100.0},
        ]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert result["holding_count"] == 1
        assert len(result["holdings"]) == 1
        assert result["holdings"][0]["symbol"] == "TCS"

    def test_all_non_dict_rows_yields_empty_snapshot(self):
        raw = ["a", "b", None, 1, ["nested", "list"]]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert result["holding_count"] == 0
        assert result["holdings"] == []

    def test_mixed_rows_preserves_order_of_dict_rows(self):
        raw = [
            "not-a-dict",
            {"trading_symbol": "INFY", "quantity": 5, "last_price": 1500.0},
            None,
            {"trading_symbol": "RELIANCE", "quantity": 2, "last_price": 2400.0},
        ]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert result["holding_count"] == 2
        assert [h["symbol"] for h in result["holdings"]] == ["INFY", "RELIANCE"]

    def test_holding_count_excludes_non_dict_rows_even_when_cap_exceeded(self):
        """holding_count must be the number of *usable* rows, not len(raw)."""
        dict_rows = [
            {"trading_symbol": f"S{i}", "quantity": 1, "last_price": 10.0}
            for i in range(MAX_STORED_HOLDINGS + 3)
        ]
        garbage = ["bad", None, 99]
        raw = dict_rows + garbage
        result = build_holdings_snapshot(raw, fields=FIELDS)
        # holding_count must equal only the dict rows
        assert result["holding_count"] == MAX_STORED_HOLDINGS + 3
        assert len(result["holdings"]) == MAX_STORED_HOLDINGS


class TestBuildHoldingsSnapshotInvariant:
    """len(holdings) == min(holding_count, MAX_STORED_HOLDINGS) always."""

    def test_invariant_holds_for_small_portfolio(self):
        raw = [
            {"trading_symbol": f"S{i}", "quantity": 1, "last_price": 10.0}
            for i in range(5)
        ]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert len(result["holdings"]) == min(
            result["holding_count"], MAX_STORED_HOLDINGS
        )

    def test_invariant_holds_when_portfolio_exactly_at_cap(self):
        raw = [
            {"trading_symbol": f"S{i}", "quantity": 1, "last_price": 10.0}
            for i in range(MAX_STORED_HOLDINGS)
        ]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert len(result["holdings"]) == MAX_STORED_HOLDINGS
        assert result["holding_count"] == MAX_STORED_HOLDINGS

    def test_invariant_holds_when_portfolio_exceeds_cap(self):
        total = MAX_STORED_HOLDINGS + 12
        raw = [
            {"trading_symbol": f"S{i}", "quantity": 1, "last_price": 10.0}
            for i in range(total)
        ]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert result["holding_count"] == total
        assert len(result["holdings"]) == MAX_STORED_HOLDINGS
        assert len(result["holdings"]) == min(
            result["holding_count"], MAX_STORED_HOLDINGS
        )

    def test_invariant_holds_with_mixed_non_dict_rows(self):
        """Non-dict rows excluded before counting — invariant must still hold."""
        dict_rows = [
            {"trading_symbol": f"S{i}", "quantity": 1, "last_price": 10.0}
            for i in range(MAX_STORED_HOLDINGS + 3)
        ]
        raw = dict_rows + ["bad-row", None]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert len(result["holdings"]) == min(
            result["holding_count"], MAX_STORED_HOLDINGS
        )


class TestBuildHoldingsSnapshotFieldMapping:
    """Field values are projected through the HoldingFieldMap."""

    def test_broker_field_names_are_mapped_to_contract_keys(self):
        raw = [
            {"trading_symbol": "TCS", "quantity": 10, "last_price": 3500.0, "pnl": 50.0}
        ]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        row = result["holdings"][0]
        assert row["symbol"] == "TCS"
        assert row["qty"] == 10
        assert row["ltp"] == 3500.0
        assert row["pnl"] == 50.0

    def test_missing_broker_field_yields_none_for_that_key(self):
        """A row that omits `pnl` must still produce a row; pnl maps to None."""
        raw = [{"trading_symbol": "TCS", "quantity": 10, "last_price": 3500.0}]
        result = build_holdings_snapshot(raw, fields=FIELDS)
        assert result["holdings"][0]["pnl"] is None
        # Symbol, qty, ltp must still be present.
        assert result["holdings"][0]["symbol"] == "TCS"


class TestMakeHoldingsParser:
    def test_extracts_holdings_from_default_data_key(self):
        parser = make_holdings_parser(fields=FIELDS)
        body = {
            "data": [
                {
                    "trading_symbol": "TCS",
                    "quantity": 10,
                    "last_price": 3500.0,
                    "pnl": 50.0,
                }
            ]
        }
        result = parser(body)
        assert result["holding_count"] == 1
        assert result["holdings"][0]["symbol"] == "TCS"
        assert result["holdings"][0]["pnl"] == 50.0

    def test_custom_data_key_is_respected(self):
        parser = make_holdings_parser(fields=FIELDS, data_key="holdings")
        body = {
            "holdings": [
                {"trading_symbol": "INFY", "quantity": 5, "last_price": 1500.0}
            ]
        }
        result = parser(body)
        assert result["holding_count"] == 1
        assert result["holdings"][0]["symbol"] == "INFY"

    def test_none_body_produces_empty_snapshot(self):
        parser = make_holdings_parser(fields=FIELDS)
        result = parser(None)
        assert result["holding_count"] == 0
        assert result["holdings"] == []

    def test_missing_data_key_in_body_produces_empty_snapshot(self):
        parser = make_holdings_parser(fields=FIELDS)
        result = parser({"wrong_key": [{"trading_symbol": "TCS"}]})
        assert result["holding_count"] == 0
        assert result["holdings"] == []

    def test_non_list_under_data_key_produces_empty_snapshot(self):
        parser = make_holdings_parser(fields=FIELDS)
        result = parser({"data": "not-a-list"})
        assert result["holding_count"] == 0
        assert result["holdings"] == []
