"""Render per-deploy regression verdict service.

Three modules, each with a single concern:

  models.py   - typed Pydantic structures; LogRecord.level is required and
                 coerced so it is never dropped before classification.
  client.py   - async Render API calls (deploy record, logs, metrics);
                 accepts an explicit httpx.AsyncClient and clock parameters.
  verdict.py  - pure verdict logic; no I/O, no clock reads; all functions
                 accept explicit window/clock values for testability.

Dependencies point inward only: client imports models; verdict imports models.
Nothing in this package imports src/api or src/integrations.
"""
