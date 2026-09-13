"""Pure parsing of what a provider's sync() left in Integration.config.

No ORM, no HTTP, no registry: every function here takes plain JSON-ish
values and returns schema objects or primitives, so the defensive rules
below are unit-testable against a dict without a DB fixture.

Defensive by design. Integration.config is JSONB written by
src/integrations/personal/{upstox,zerodha_kite}.py against two third-party
APIs, so every shape it could hold -- missing, null, non-list, non-dict
rows, absent symbols, string-typed numerics -- is handled rather than
allowed to raise. The endpoint's contract is always-200; a malformed
snapshot must degrade to fewer rows, never to a 500.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from ...schemas.finance import Holding

_log = logging.getLogger(__name__)

# Read-side twin of _holdings_snapshot.MAX_CELL_CHARS. The write side bounds
# what new syncs store; this bounds what is *served*, which also covers rows
# persisted before that bound existed. `symbol` is the only free-text field
# on the wire -- every other one is coerced through to_float -- so it is the
# only one that can carry an unbounded upstream string into the response
# body and the DOM.
MAX_SYMBOL_CHARS = 64


def to_float(v: object) -> float | None:
    """Best-effort numeric coercion for a JSONB leaf value.

    `bool` is rejected before the `int` check -- in Python `True` is an
    instance of `int` and would otherwise silently become `1.0`. Kite has
    historically returned some numerics as strings, hence the str branch.
    NaN/inf are rejected because they are not valid JSON and would produce
    a non-parseable response body.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        result = float(v)
    elif isinstance(v, str):
        try:
            result = float(v.strip())
        except (ValueError, TypeError):
            return None
    else:
        return None
    return result if math.isfinite(result) else None


def iso_utc(dt: datetime | None) -> str | None:
    """Serialise with an explicit UTC offset.

    A naive datetime's bare `.isoformat()` is parsed by `new Date(...)` in
    the browser as *local* time, silently shifting the "as of" label by the
    user's UTC offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def as_config(raw: object, *, slug: str | None = None) -> dict[str, Any]:
    """Integration.config narrowed to a dict -- it is nullable in the DB.

    `None` is the normal case (a broker that has never synced) and is not
    logged. Any other non-dict value means sync() wrote something the JSONB
    column was never meant to hold: still silent to the user, but logged,
    because it otherwise renders as an unexplained empty portfolio for a
    connected, synced broker.
    """
    if isinstance(raw, dict):
        return raw
    if raw is not None:
        _log.warning(
            "Integration.config for broker %r was %s, not a dict/null -- "
            "treating as empty",
            slug,
            type(raw).__name__,
        )
    return {}


def parse_holdings(config: dict[str, Any], *, slug: str | None = None) -> list[Holding]:
    """The `holdings` array, normalised into renderable rows.

    A row missing a usable `symbol` is skipped rather than rendered blank:
    there is nothing meaningful to show for it. `value` is computed here,
    server-side, so the frontend never does arithmetic on a nullable field.

    A skip is harmless for a stray malformed upstream row and a real
    problem if sync() itself is broken -- indistinguishable to the user
    either way, so skips are logged once per call (not per row, which would
    flood the logs on a badly malformed portfolio).
    """
    raw = config.get("holdings")
    if isinstance(raw, list):
        rows: list[Any] = raw
    else:
        rows = []
        if raw is not None:
            _log.warning(
                "Integration.config['holdings'] for broker %r was %s, not a "
                "list -- treating as empty",
                slug,
                type(raw).__name__,
            )

    holdings: list[Holding] = []
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        symbol = row.get("symbol")
        if symbol is None or str(symbol).strip() == "":
            skipped += 1
            continue
        qty = to_float(row.get("qty"))
        ltp = to_float(row.get("ltp"))
        pnl = to_float(row.get("pnl"))
        value = qty * ltp if qty is not None and ltp is not None else None
        holdings.append(
            Holding(
                symbol=str(symbol)[:MAX_SYMBOL_CHARS],
                qty=qty,
                ltp=ltp,
                pnl=pnl,
                value=value,
            )
        )
    if skipped:
        _log.warning(
            "Skipped %d malformed holding row(s) for broker %r (missing/"
            "invalid symbol or non-dict row)",
            skipped,
            slug,
        )
    return holdings


def resolve_holding_count(
    config: dict[str, Any], shown: int, *, slug: str | None = None
) -> int:
    """The portfolio's true size, never smaller than what is on screen.

    Falls back to the number of rendered rows when `holding_count` is
    absent or unparseable, then clamps up: a stale or missing stored count
    must never understate what is actually being displayed, because
    `truncated` (and the "showing top N of M" caption) is derived from it.
    """
    stored = config.get("holding_count")
    raw_count = to_float(stored)
    if stored is not None and raw_count is None:
        _log.warning(
            "Integration.config['holding_count'] for broker %r was %r, "
            "not numeric -- falling back to the rendered row count",
            slug,
            stored,
        )
    holding_count = int(raw_count) if raw_count is not None else shown
    return max(holding_count, shown)
