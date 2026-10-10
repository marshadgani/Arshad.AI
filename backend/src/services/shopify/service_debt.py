"""Match unanswered Gmail threads to Shopify orders. Pure: no I/O.

Gmail has already applied the age and last-sender rules through its query
(`in:inbox -from:me older_than:24h`); this module only attaches order
context and orders the list.
"""

from __future__ import annotations

import html
import re
from typing import Any

from ...schemas.shopify import ThreadMeta

_HASH_NUMBER = re.compile(r"(?<![\w#])#(\d+)\b")
_ORDER_WORD_NUMBER = re.compile(
    r"\border\s+(?:number\s+|no\.?\s*)?#?(\d+)\b", re.IGNORECASE
)
_MIN_NAME_TOKENS = 2


def _order_key(name: str | None) -> str | None:
    key = (name or "").lstrip("#").strip()
    return key or None


def _name_pattern(display_name: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<!\w)" + re.escape(display_name) + r"(?!\w)", re.IGNORECASE
    )


def _match_one(
    snippet: str,
    by_number: dict[str, dict],
    named: list[tuple[re.Pattern[str], dict]],
):
    for number in _HASH_NUMBER.findall(snippet):
        if number in by_number:
            return by_number[number], "high"
    for number in _ORDER_WORD_NUMBER.findall(snippet):
        if number in by_number:
            return by_number[number], "low"
    for pattern, order in named:
        if pattern.search(snippet):
            return order, "low"
    return None, None


def match_threads_to_orders(
    threads: list[dict[str, Any]], orders: list[dict[str, Any]]
) -> list[ThreadMeta]:
    """Attach the best-matching order to each thread, using the snippet only.

    Order references ("#1042") are high confidence; "order 1042" and a
    customer's full display name are low confidence. Order references win
    over names, and the newest order wins among name matches (orders arrive
    newest first).

    False positives: a snippet may quote a number or name that belongs to a
    different conversation (a forwarded receipt, a shared surname), and
    "#1042" can be an unrelated reference. False negatives: the snippet is a
    ~100 character preview, so a thread that names its order only further
    down, or a customer who writes from another name, shows no order. Only
    two-or-more-word customer names are matched, to avoid first-name
    collisions. The snippet-only rule is deliberate: no per-thread
    threads.get calls.
    """
    by_number: dict[str, dict] = {}
    # Patterns are compiled once per distinct customer, not once per
    # thread x order: up to 100 threads against hundreds of orders would
    # otherwise overflow re's 512-entry cache and recompile on every search.
    named: list[tuple[re.Pattern[str], dict]] = []
    seen_names: set[str] = set()
    for order in orders:
        key = _order_key(order.get("name"))
        if key and key not in by_number:
            by_number[key] = order
        customer = ((order.get("customer") or {}).get("displayName") or "").strip()
        folded = customer.casefold()
        if len(customer.split()) >= _MIN_NAME_TOKENS and folded not in seen_names:
            seen_names.add(folded)
            named.append((_name_pattern(customer), order))

    result: list[ThreadMeta] = []
    for thread in threads:
        snippet = html.unescape(thread.get("snippet") or "")
        order, confidence = _match_one(snippet, by_number, named)
        result.append(
            ThreadMeta(
                id=str(thread.get("id")),
                snippet=snippet,
                matched_order_id=order.get("id") if order else None,
                matched_order_name=order.get("name") if order else None,
                match_confidence=confidence,
            )
        )
    return result


def rank_threads(threads: list[ThreadMeta]) -> list[ThreadMeta]:
    """Oldest first. threads.list returns newest first and carries no
    timestamp we rely on, so reversing is the only ordering available.
    """
    return list(reversed(threads))
