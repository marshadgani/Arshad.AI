"""Brokerage holdings read model for the /finance and /stocks pages.

Layered like src/services/shopify/:

  brokers.py   — the brokerage catalogue: which slugs this feature covers,
                 in what order, their currency and display names. The only
                 module here that touches INTEGRATION_REGISTRY.
  parsers.py   — pure Integration.config -> Holding parsing plus the leaf
                 numeric/datetime coercions. No ORM, no HTTP, no registry.
  holdings.py  — assembles the BrokerHoldings / FinanceHoldingsResponse
                 read model from Integration rows.

Dependencies point one way: holdings -> brokers/parsers, everything ->
schemas. Nothing here imports src/api.

Split out of src/api/v1/finance.py, which had accumulated the catalogue,
the coercions, the row projection and the gather loop alongside its HTTP
concerns. Behaviour is unchanged: the same functions, in the same order,
producing the same payload.

This is a read model over data that src/integrations/personal/{upstox,
zerodha_kite}.py::sync() already persisted into Integration.config. Nothing
here performs a provider fetch, and nothing here writes.
"""
