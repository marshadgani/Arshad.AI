"""Shared error contract for the ingestion layer.

``IngestionError`` lives here, not in ``runner.py``, because every
per-DAG module raises it while ``runner.py`` imports every per-DAG
module. Defining it on the dispatcher made the dependency cyclic.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Raised when a runner can't proceed for a known reason."""
