"""The write side of the brokerage holdings contract.

Every broker sync() persists its portfolio into Integration.config under
the same two keys: `holding_count` (the size of the portfolio the broker
reported) and `holdings` (a bounded snapshot of {symbol, qty, ltp, pnl}
rows). This module is the only place that shape is produced.

Why it is its own module rather than inline in each provider: the read
model in src/services/finance/parsers.py is written to be defensive about
exactly these two keys, and it can only stay coherent if there is one
writer to be defensive about. With the contract stated here, a broker
declares *its own field names* (a mapping) and nothing else -- adding a
third broker cannot accidentally invent a third snapshot shape, and
changing the snapshot shape is a one-file change on each side of the
contract rather than an edit spread across every provider.

Defensive for the same reason parsers.py is: `data` comes from a
third-party API, so a missing/null/non-list payload, or a non-dict row
within it, degrades to a smaller snapshot rather than raising
(AttributeError on `.get`, TypeError on slicing) and leaving
integration.status stuck at whatever it was before the sync.

Nothing here performs I/O or touches the ORM -- it maps plain JSON-ish
values to plain JSON-ish values, so it is unit-testable without a DB
fixture or a mocked transport.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

# Self-imposed bound on how many holding rows a broker sync stores in
# Integration.config["holdings"] (a JSONB snapshot) -- NOT a broker API
# limit. The full portfolio size is still recorded separately as
# holding_count, so the read path's `truncated` flag stays accurate even
# when the snapshot itself is capped.
MAX_STORED_HOLDINGS: int = 10

# Upper bound on a single snapshot cell. The row cap above bounds how many
# rows a broker response can push into the JSONB column, but not how large
# one row is: every cell is whatever the third-party API put under that key,
# which may be a megabyte-long string or an arbitrarily nested object. That
# is unvalidated third-party input written to our database and then served
# back on GET /api/v1/finance/holdings, so it is bounded here at the only
# write site rather than trusted to stay small.
MAX_CELL_CHARS: int = 64

# snapshot key -> the key that broker's API uses for it. Declared per
# provider; the snapshot keys themselves are fixed by the contract above.
HoldingFieldMap = Mapping[str, str]


def _cell(value: object) -> Any:
    """One snapshot cell, narrowed to a bounded JSON scalar.

    A broker is contracted to return a symbol/quantity/price/pnl here. A
    dict or list under one of those keys is not something the read model
    can render (parsers.to_float rejects it, and `str(symbol)` on a dict
    would render its repr), so it is dropped rather than persisted. Strings
    are truncated: the read path stringifies `symbol` straight onto the
    page, so an unbounded one is unbounded DB write, response size and DOM
    text from an upstream we do not control.
    """
    if isinstance(value, str):
        return value[:MAX_CELL_CHARS]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return None


def build_holdings_snapshot(raw: object, *, fields: HoldingFieldMap) -> dict[str, Any]:
    """`raw` (a broker's holdings array) as the config snapshot pair.

    Unusable rows are dropped *before* counting, so `holding_count` is the
    number of rows that could actually have been rendered. That keeps
    `len(holdings) == min(holding_count, MAX_STORED_HOLDINGS)` an
    invariant, which is what makes the read path's `truncated` flag (and
    the "showing top N of M" caption derived from it) exact rather than
    merely an upper bound.
    """
    rows = (
        [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    )
    return {
        "holding_count": len(rows),
        "holdings": [
            {key: _cell(row.get(broker_key)) for key, broker_key in fields.items()}
            for row in rows[:MAX_STORED_HOLDINGS]
        ],
    }


def make_holdings_parser(
    *, fields: HoldingFieldMap, data_key: str = "data"
) -> Callable[[Any], dict[str, Any]]:
    """A `parse_sync` for make_oauth_sync_via_api, for one broker's shape.

    Both supported brokers wrap their holdings array in a top-level
    `data` key; `data_key` exists so a third one that doesn't is a
    keyword argument rather than a reason to hand-roll the parser again.

    `body` is narrowed to a Mapping rather than assumed to be one. It is
    whatever `resp.json()` decoded, i.e. attacker-adjacent third-party
    input: a bare JSON array, a JSON string, or a number all satisfy
    `raise_for_status()` and would otherwise reach `.get` and raise
    AttributeError. That exception is caught by make_oauth_sync_via_api's
    guard, so it never 500s -- but it lands as an opaque
    "AttributeError: 'list' object has no attribute 'get'" in
    Integration.last_error, which reads like a bug in our own code rather
    than the envelope change it actually is. Degrading to an empty
    snapshot keeps the module's stated contract ("missing/null/non-list
    payload degrades rather than raises") true for the envelope as well as
    for the rows inside it.
    """

    def _parse(body: Any) -> dict[str, Any]:
        raw = body.get(data_key) if isinstance(body, Mapping) else None
        return build_holdings_snapshot(raw, fields=fields)

    return _parse
