"""Dashboard weather read model.

Layered like src/services/shopify/:

  conditions.py   — pure wire/cache payload -> CurrentConditions parsing.
                    No ORM, no HTTP, no Redis, no response schema.
  cache.py        — fail-open Redis cache for the parsed tile.
  credentials.py  — the single seam onto the stored, encrypted API key.
  presentation.py — assembles the four WeatherResponse tile states
                    (live / needs_reauth / degraded / never_connected).
  service.py      — the orchestration, and nothing else: integration
                    lookup, cache, credential load, upstream call, status
                    transitions, and which tile state each branch ends in.

Dependencies point one way: service -> presentation/credentials/
conditions/cache -> schemas. presentation and credentials never import
service, so the decision tree can change without touching either, and each
is unit-testable without a database, a Redis, or a network.
Nothing here imports src/api.

**Keep this file free of submodule imports.** ``integrations/personal/
openweathermap.py`` imports ``services.weather.cache`` to invalidate the
tile, while ``service.py`` imports that same provider module for its
upstream egress point. An eager re-export here would close that loop into
an ImportError at startup — the same hazard documented in
``integrations/personal/shopify.py``.
"""
