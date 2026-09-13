"""Tunables shared by every ingestion runner in this package.

One definition of the batch cap for calendar.py, email.py and github.py,
so changing the default, the clamp or the env var name is a single edit.
"""

from __future__ import annotations

import os

import annotated_types
from pydantic import BaseModel

_BATCH_SIZE_ENV = "MAX_INGEST_BATCH_SIZE"
_DEFAULT_BATCH_SIZE = 100


def field_upper_bound(model: type[BaseModel], field: str) -> int | None:
    """The ``le=`` constraint declared on ``model``'s ``field``, if any.

    Lets a runner clamp to its provider tool's real limit without
    restating that number. Restating it is what caused the outage this
    exists to prevent: ``max_batch_size()`` is a single env var shared by
    runners whose tools cap ``max_results`` differently (GitHub and Gmail
    at 100, Calendar at 250), and nothing reconciled the two contracts.
    Reading the bound off the schema means raising a tool's ``le=`` is
    picked up automatically instead of needing a matching edit here.

    Returns ``None`` when the field declares no upper bound, so callers
    can distinguish "unbounded" from a bound that happens to be small.
    """
    metadata = model.model_fields[field].metadata
    bounds = [m.le for m in metadata if isinstance(m, annotated_types.Le)]
    return min(bounds) if bounds else None


def max_batch_size(ceiling: int | None = None) -> int:
    """Per-provider fetch cap for a single ingestion run.

    Read at call time (not import time) so tests and the queue worker can
    change the environment between runs. A non-numeric value falls back to
    the default rather than failing the run; a numeric one is clamped to
    at least 1, because a cap of 0 would make every run a silent no-op.

    ``ceiling`` is the caller's own hard upper bound — normally its
    provider tool's ``max_results`` limit, via ``field_upper_bound()``.
    Clamping down to it here is what makes this value *always* safe to
    hand to that tool. Without it the clamp is only half a clamp: raising
    ``MAX_INGEST_BATCH_SIZE`` above a tool's limit turns every call into a
    ``ValidationError``, which is not one of the failure types a runner
    isolates per-item, so the whole run dies rather than degrading.
    """
    try:
        size = max(1, int(os.getenv(_BATCH_SIZE_ENV, str(_DEFAULT_BATCH_SIZE))))
    except ValueError:
        size = _DEFAULT_BATCH_SIZE
    if ceiling is None:
        return size
    # max(1, ceiling) guards a nonsensical caller-supplied ceiling from
    # re-introducing the zero-batch silent no-op ruled out above.
    return min(size, max(1, ceiling))
