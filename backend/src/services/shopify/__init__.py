"""Shopify Admin API live-read-model integration.

Layered like src/services/whoop/:

  client.py          — the only module that speaks HTTP to Shopify (GraphQL
                       reads + the per-shop OAuth token exchange)
  parsers.py         — pure wire-to-schema parsing and metric derivation
  dashboard.py       — assembles the ShopifyDashboard response (live + degraded)
  state.py           — binds the shared integration lifecycle to the 'shopify'
                       slug and owns the Integration.config read shape
  tokens.py          — the single deferred-import seam into the provider layer
  cache.py           — fail-open Redis dashboard cache

Intelligence-layer additions (FEAT-125):

  gather.py          — concurrent Shopify fetch orchestration, throttle-fallback
                       logic, result-processing primitives, and the business
                       constants (VELOCITY_WINDOW_DAYS etc.) shared across routes
  providers.py       — Google Calendar and Gmail fetch functions plus structured
                       result-parsing dataclasses (CalendarResult, GmailResult)
                       that eliminate the ProviderNotLinked/ProviderReauthRequired
                       isinstance dispatch from every route handler
  inventory_cover.py — days-of-cover computation and travel-window stockout alerts
  discount.py        — discount break-even evaluation
  service_debt.py    — Gmail-to-Shopify-order thread matching and ranking

Dependencies point one way: dashboard/inventory_cover/discount/service_debt ->
parsers/state, gather/providers are imported by routes only. Nothing here
imports src/api.

No data is persisted to Postgres — this is a live read model, not an
ingestion pipeline. Shopify's read_orders scope only exposes 60 days of
history for non-Plus apps, so historical analysis must not be built on top
of this module.
"""
