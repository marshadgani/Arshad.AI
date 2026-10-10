"""HTTP transport for the Shopify Admin API — the ONLY module that talks to
Shopify over the wire.

Knows nothing about FastAPI, the database, or the Integration model — a
change to Shopify's HTTP surface is contained entirely here, mirroring
src/services/whoop/client.py. That includes the OAuth token exchange
(exchange_oauth_code below), which the provider calls rather than hand-
rolling its own httpx client: the provider decides *when* to exchange a
code, this module decides *how* to reach Shopify.

Uses the Admin GraphQL API (X-Shopify-Access-Token header, NOT
Authorization: Bearer). GraphQL returns HTTP 200 with an `errors` array on
partial failure — resp.raise_for_status() alone is not sufficient, so every
alias is read independently and a failure in one never blocks the others.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from typing import Any

import httpx

from ...integrations.base import IntegrationError

# Expires ~July 2027. Backlog item queued: `python scripts/backlog_add.py
# --title 'Update Shopify API version from 2026-07' --autonomous yes`
SHOPIFY_API_VERSION = "2026-07"

REQUEST_TIMEOUT_SECONDS = 15.0

# Page sizes are GraphQL variables, not literals inside the query text, so
# each is stated exactly once. ORDERS_PAGE_LIMIT is echoed back in the
# returned dict (`orders_page_limit`) because the parser's truncation rule
# is defined relative to it — see parsers.parse_dashboard.
ORDERS_PAGE_LIMIT = 250
VARIANTS_PAGE_LIMIT = 250
# Orders with line items are far costlier than the dashboard's lineItems(first:1):
# Shopify prices a connection as first x its children, and a single query may
# not exceed 1000 points. 50 orders x 10 line items stays well under that, so
# the velocity window is a bounded sample and the result reports truncation
# (orders_has_next_page / line_items_truncated) instead of a confident number.
VELOCITY_ORDERS_PAGE_LIMIT = 50
LINE_ITEMS_PAGE_LIMIT = 10

# Shopify's leaky-bucket capacity for a standard (non-Plus) app, used only
# to scale the THROTTLED back-off — a wrong value slows retries, it does not
# break them.
THROTTLE_BUCKET_POINTS = 50
MAX_THROTTLE_RETRIES = 1

_log = logging.getLogger(__name__)

_DASHBOARD_QUERY = """
query DashboardData($ordersQuery: String!, $ordersFirst: Int!, $variantsFirst: Int!) {
  orders(first: $ordersFirst, query: $ordersQuery, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage }
    edges {
      node {
        id
        name
        createdAt
        currentTotalPriceSet { shopMoney { amount currencyCode } }
        lineItems(first: 1) { totalCount }
        customer { displayName }
      }
    }
  }
  ordersCount(query: $ordersQuery) { count precision }
  productVariants(first: $variantsFirst) {
    pageInfo { hasNextPage }
    edges {
      node {
        id
        inventoryItem {
          tracked
          inventoryLevels(first: 10) {
            edges { node { quantities(names: ["available"]) { name quantity } } }
          }
        }
      }
    }
  }
}
"""


_ORDERS_QUERY = """
query OrdersSince(
  $ordersQuery: String!, $first: Int!, $withLines: Boolean!, $linesFirst: Int!
) {
  orders(first: $first, query: $ordersQuery, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage }
    edges {
      node {
        id
        name
        customer { displayName }
        lineItems(first: $linesFirst) @include(if: $withLines) {
          pageInfo { hasNextPage }
          edges { node { quantity variant { id } } }
        }
      }
    }
  }
}
"""

# No product price here on purpose: inventory cover never uses it, and it
# would spend leaky-bucket points on every one of the page's variants.
_VARIANT_INVENTORY_QUERY = """
query VariantInventory($variantsFirst: Int!) {
  productVariants(first: $variantsFirst) {
    pageInfo { hasNextPage }
    edges {
      node {
        id
        inventoryItem {
          tracked
          inventoryLevels(first: 10) {
            edges { node { quantities(names: ["available"]) { name quantity } } }
          }
        }
      }
    }
  }
}
"""

_DISCOUNT_VARIANT_QUERY = """
query DiscountVariant($id: ID!) {
  productVariant(id: $id) {
    price
    inventoryItem { unitCost { amount currencyCode } }
  }
}
"""


def _shop_hash(shop: str) -> str:
    """SHA-256 prefix of the shop domain — safe to log, never the raw domain."""
    return hashlib.sha256(shop.encode("utf-8")).hexdigest()[:16]


def _graphql_url(shop: str) -> str:
    return f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }


async def exchange_oauth_code(
    *, shop: str, client_id: str, client_secret: str, code: str
) -> dict[str, Any]:
    """Trade an authorization code for a Shopify offline access token.

    Shopify's token endpoint is per-shop, which is why this cannot go
    through OAuthIntegrationProvider.exchange_code (single fixed token_url,
    form-encoded). `shop` must already be a validated, Redis-stored domain
    — see integrations/personal/shopify_oauth.validate_shop_domain — because
    it becomes the request host.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise IntegrationError(
            "token_exchange_failed",
            f"Shopify token exchange returned {resp.status_code}: {resp.text[:200]}",
        )
    token_response = resp.json()
    if not token_response.get("access_token"):
        raise IntegrationError("no_access_token", "Shopify returned no access_token.")
    return token_response


async def execute_dashboard_query(
    shop: str, token: str, day_start: str, day_end: str
) -> dict[str, Any]:
    """Fetch orders/ordersCount/productVariants for the dashboard.

    Returns a dict with keys: orders (list of edge nodes), orders_has_next_page,
    orders_count (int|None), orders_count_precision (str|None),
    orders_page_limit (int), variants (list of edge nodes),
    variants_has_next_page (bool), partial_failures (list[str]).

    Orders are fetched newest-first (reverse: true) because the dashboard's
    "Recent Orders" feed shows the head of this list. Ascending order would
    surface the day's OLDEST orders, and on a >250-order day would drop the
    newest ones entirely.

    Low-stock thresholding is applied client-side in parsers.py against
    parsers.LOW_STOCK_DEFAULT_THRESHOLD — this query fetches one
    VARIANTS_PAGE_LIMIT-sized page and reports variants_has_next_page so a
    consumer can tell a complete count from a partial one.
    """
    orders_query = f"created_at:>='{day_start}' created_at:<='{day_end}' test:false"
    variables = {
        "ordersQuery": orders_query,
        "ordersFirst": ORDERS_PAGE_LIMIT,
        "variantsFirst": VARIANTS_PAGE_LIMIT,
    }

    body = await _post_with_retry(
        _graphql_url(shop), _auth_headers(token), _DASHBOARD_QUERY, variables, shop
    )

    partial_failures = _log_graphql_errors(body, shop, context="dashboard")

    data = body.get("data") or {}
    cost = (body.get("extensions") or {}).get("cost") or {}
    if cost:
        _log.info(
            "Shopify GraphQL cost shop_hash=%s requested=%s actual=%s",
            _shop_hash(shop),
            cost.get("requestedQueryCost"),
            cost.get("actualQueryCost"),
        )

    orders_block = data.get("orders") or {}
    orders_count_block = data.get("ordersCount") or {}
    variants_block = data.get("productVariants") or {}

    return {
        "orders": [e.get("node") for e in (orders_block.get("edges") or [])],
        "orders_has_next_page": bool(
            (orders_block.get("pageInfo") or {}).get("hasNextPage")
        ),
        "orders_count": orders_count_block.get("count"),
        "orders_count_precision": orders_count_block.get("precision"),
        "orders_page_limit": ORDERS_PAGE_LIMIT,
        "variants": [e.get("node") for e in (variants_block.get("edges") or [])],
        "variants_has_next_page": bool(
            (variants_block.get("pageInfo") or {}).get("hasNextPage")
        ),
        "partial_failures": partial_failures,
    }


def _log_cost(body: dict[str, Any], shop: str) -> None:
    cost = (body.get("extensions") or {}).get("cost") or {}
    if cost:
        _log.info(
            "Shopify GraphQL cost shop_hash=%s requested=%s actual=%s",
            _shop_hash(shop),
            cost.get("requestedQueryCost"),
            cost.get("actualQueryCost"),
        )


async def execute_orders_query(
    shop: str,
    token: str,
    since_iso: str,
    *,
    with_line_items: bool = True,
    max_retries: int = MAX_THROTTLE_RETRIES,
) -> dict[str, Any]:
    """Orders created at/after `since_iso`, newest first.

    `since_iso` is a caller-supplied anchor (never read from the clock here)
    so tests can pin the window, as with execute_dashboard_query. Without
    line items (service-debt only needs order names and customers) a full
    ORDERS_PAGE_LIMIT page is cheap enough to fetch.

    Returns orders (nodes), orders_has_next_page, line_items_truncated,
    partial_failures, throttled (True when the final attempt was THROTTLED,
    in which case orders is empty).
    """
    page = VELOCITY_ORDERS_PAGE_LIMIT if with_line_items else ORDERS_PAGE_LIMIT
    variables = {
        "ordersQuery": f"created_at:>='{since_iso}' test:false",
        "first": page,
        "withLines": with_line_items,
        "linesFirst": LINE_ITEMS_PAGE_LIMIT,
    }
    body = await _post_with_retry(
        _graphql_url(shop),
        _auth_headers(token),
        _ORDERS_QUERY,
        variables,
        shop,
        max_retries=max_retries,
    )
    partial_failures = _log_graphql_errors(body, shop, context="orders")
    _log_cost(body, shop)

    block = (body.get("data") or {}).get("orders") or {}
    nodes = [e.get("node") or {} for e in (block.get("edges") or [])]
    return {
        "orders": nodes,
        "orders_has_next_page": bool((block.get("pageInfo") or {}).get("hasNextPage")),
        "line_items_truncated": any(
            ((n.get("lineItems") or {}).get("pageInfo") or {}).get("hasNextPage")
            for n in nodes
        ),
        "partial_failures": partial_failures,
        "throttled": _throttled_error(body) is not None,
    }


async def execute_variant_inventory_query(
    shop: str, token: str, *, max_retries: int = MAX_THROTTLE_RETRIES
) -> dict[str, Any]:
    """One VARIANTS_PAGE_LIMIT page of variants with available quantities.

    Returns variants (nodes), variants_has_next_page, partial_failures,
    throttled.
    """
    body = await _post_with_retry(
        _graphql_url(shop),
        _auth_headers(token),
        _VARIANT_INVENTORY_QUERY,
        {"variantsFirst": VARIANTS_PAGE_LIMIT},
        shop,
        max_retries=max_retries,
    )
    partial_failures = _log_graphql_errors(body, shop, context="variant_inventory")
    _log_cost(body, shop)

    block = (body.get("data") or {}).get("productVariants") or {}
    return {
        "variants": [e.get("node") or {} for e in (block.get("edges") or [])],
        "variants_has_next_page": bool(
            (block.get("pageInfo") or {}).get("hasNextPage")
        ),
        "partial_failures": partial_failures,
        "throttled": _throttled_error(body) is not None,
    }


async def execute_discount_variant_query(
    shop: str, token: str, variant_id: str, *, max_retries: int = MAX_THROTTLE_RETRIES
) -> dict[str, Any]:
    """Price and unit cost of one variant. `variant_id` must already be
    validated (schemas.shopify.DiscountSimulatorRequest) — it is a GraphQL
    variable, not interpolated into the query.

    Returns variant (node or None), partial_failures, throttled.
    """
    body = await _post_with_retry(
        _graphql_url(shop),
        _auth_headers(token),
        _DISCOUNT_VARIANT_QUERY,
        {"id": variant_id},
        shop,
        max_retries=max_retries,
    )
    partial_failures = _log_graphql_errors(body, shop, context="discount_variant")
    _log_cost(body, shop)
    return {
        "variant": (body.get("data") or {}).get("productVariant"),
        "partial_failures": partial_failures,
        "throttled": _throttled_error(body) is not None,
    }


_SHOP_METADATA_QUERY = "{ shop { name ianaTimezone currencyCode } }"


async def fetch_shop_metadata(shop: str, token: str) -> dict[str, Any]:
    """Lightweight probe used at OAuth callback time and by sync().

    Separate from the dashboard query — it needs no order/variant data and
    costs ~1 point, so it is safe to call on every reconnect and refresh.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            _graphql_url(shop),
            json={"query": _SHOP_METADATA_QUERY},
            headers=_auth_headers(token),
        )
        resp.raise_for_status()
        body = resp.json()
    # resp.raise_for_status() only rules out a transport-level failure —
    # GraphQL reports permission/query errors as HTTP 200 with an `errors`
    # array (see module docstring). Without this, a missing scope or a
    # malformed query silently produces an empty `shop` dict, which the
    # caller then persists as defaulted UTC/USD with no trace anywhere.
    _log_graphql_errors(body, shop, context="shop_metadata")

    shop_data = ((body.get("data") or {}).get("shop")) or {}
    return {
        "name": shop_data.get("name"),
        "ianaTimezone": shop_data.get("ianaTimezone"),
        "currencyCode": shop_data.get("currencyCode"),
    }


def _guess_alias(err: dict[str, Any]) -> str:
    path = err.get("path") or []
    return str(path[0]) if path else "unknown"


def _log_graphql_errors(body: dict[str, Any], shop: str, *, context: str) -> list[str]:
    """Warn on every GraphQL error in `body`, and return the aliases they hit.

    GraphQL reports partial failure as HTTP 200 with an `errors` array, so
    this is the only place either query learns something went wrong. The
    returned aliases become the response's `partial_failures`.
    """
    aliases: list[str] = []
    for err in body.get("errors") or []:
        alias = _guess_alias(err)
        _log.warning(
            "Shopify GraphQL error context=%s shop_hash=%s alias=%s code=%s message=%s",
            context,
            _shop_hash(shop),
            alias,
            (err.get("extensions") or {}).get("code"),
            err.get("message"),
        )
        aliases.append(alias)
    return aliases


def _throttled_error(body: dict[str, Any]) -> dict[str, Any] | None:
    """The first THROTTLED entry in a GraphQL error array, if there is one."""
    for err in body.get("errors") or []:
        if (err.get("extensions") or {}).get("code") == "THROTTLED":
            return err
    return None


def _throttle_delay(err: dict[str, Any]) -> float:
    """Back-off for a THROTTLED error: longer the less leaky-bucket capacity
    Shopify reports, plus jitter so concurrent requests do not retry in step.
    """
    cost = (err.get("extensions") or {}).get("cost") or {}
    available = (cost.get("throttleStatus") or {}).get("currentlyAvailable", 0)
    return max(0.5, (THROTTLE_BUCKET_POINTS - available) / THROTTLE_BUCKET_POINTS) + (
        random.uniform(0, 0.25)
    )


async def _post_with_retry(
    url: str,
    headers: dict[str, str],
    query: str,
    variables: dict[str, Any],
    shop: str,
    *,
    max_retries: int = MAX_THROTTLE_RETRIES,
) -> dict[str, Any]:
    """POST the GraphQL request. Up to `max_retries` retries, with jitter, on
    THROTTLED. Callers that are already a fallback for a throttled call pass
    0 so retry budgets do not multiply.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for attempt in range(max_retries + 1):
            resp = await client.post(
                url, json={"query": query, "variables": variables}, headers=headers
            )
            resp.raise_for_status()
            body = resp.json()

            throttled = _throttled_error(body)
            if throttled is None or attempt == max_retries:
                return body

            delay = _throttle_delay(throttled)
            _log.warning(
                "Shopify GraphQL throttled shop_hash=%s, retrying in %.2fs",
                _shop_hash(shop),
                delay,
            )
            await asyncio.sleep(delay)
        return body  # pragma: no cover — the loop always returns above
