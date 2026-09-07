"""Shopify Admin API live-read-model integration.

Layered like src/services/whoop/:

  client.py     — the only module that speaks HTTP to Shopify (GraphQL
                  reads + the per-shop OAuth token exchange)
  parsers.py    — pure wire-to-schema parsing and metric derivation
  dashboard.py  — assembles the ShopifyDashboard response (live + degraded)
  state.py      — binds the shared integration lifecycle to the 'shopify'
                  slug and owns the Integration.config read shape
  tokens.py     — the single deferred-import seam into the provider layer
  cache.py      — fail-open Redis dashboard cache

Dependencies point one way: dashboard -> parsers/state, everything ->
schemas. Nothing here imports src/api.

No data is persisted to Postgres — this is a live read model, not an
ingestion pipeline. Shopify's read_orders scope only exposes 60 days of
history for non-Plus apps, so historical analysis must not be built on top
of this module.
"""
