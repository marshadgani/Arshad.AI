"""Obsidian vault domain services.

One concern per module, so each can be read, tested and changed alone:

    config.py             vault location + render config (no HTTP)
    client.py             GitHub transport, single-request vault ops
    batch_commit.py       the multi-step Git Data commit protocol
    markdown.py           pure path/frontmatter primitives (no domain knowledge)
    renderers.py          ingested row -> RenderedNote (pure)
    domains.py            the one registry of exportable domains
    jobs.py               DagTriggerQueue plumbing for both DAGs
    export_lock.py        per-user run lock (fail-open, release-if-held)
    export_repository.py  every DB access the exporter performs
    export_planner.py     render + ledger diff, pure and network-free
    export_service.py     orchestration only
    notes_repository.py   queries backing the vault-browsing endpoints

`api/v1/obsidian.py` keeps only routing and wire-shape concerns.

The export direction is one-way (Arshad.AI -> vault) by construction:
there is no code path here that writes an ingested_* table from vault
content, and no ontology or MOC graph is generated. See renderers.py for
how the FEAT-141 boundary is enforced in code rather than by convention.
"""

from __future__ import annotations

from .config import EXPORT_ROOT, ExportConfig, resolve_vault_repo, vault_repo
from .domains import DOMAIN_NAMES
from .export_service import MAX_CHAINED_RUNS, MAX_NOTES_PER_RUN, export_notes

__all__ = [
    "DOMAIN_NAMES",
    "EXPORT_ROOT",
    "MAX_CHAINED_RUNS",
    "MAX_NOTES_PER_RUN",
    "ExportConfig",
    "export_notes",
    "resolve_vault_repo",
    "vault_repo",
]
